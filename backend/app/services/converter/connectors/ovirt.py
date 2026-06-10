"""
oVirt / RHV connector — pull a disk via the ImageTransfer download API.

Strategy (cold pull):
1. ``ovirt-engine-sdk-python``: open a Connection (mirrors ``discovery._discover_ovirt``).
2. Resolve the VM by ``source_uuid`` (preferred) or name; enumerate its
   ``disk_attachments`` -> disks (id, format, provisioned_size).
3. Open an ``ImageTransfer`` with ``direction=download`` for each disk; poll
   until the transfer reaches ``TRANSFERRING`` and exposes a URL.
4. Stream the image bytes over HTTPS (``requests``) into the destination,
   computing sha256 inline, then ``finalize`` the transfer.

``pull_disk`` lands the disk in its native format on the shared transit (the
in-cluster qemu-img Job converts). ``convert_on_source`` downloads to the worker
scratch and compresses locally with ``qemu-img`` for the SFTP bridge.

This connector talks pure HTTPS + SDK, so it works unchanged from a Linux
in-cluster worker. It has no live oVirt test environment available — it is
written against the documented SDK / imageio behaviour and covered by mocked
unit tests.
"""

from __future__ import annotations

import logging
import time
import warnings
from pathlib import Path
from typing import List, Optional

from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.connectors.base import (
    local_qemu_img_convert,
    sha256_file,
)
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)

logger = logging.getLogger(__name__)

_HASH_CHUNK = 1024 * 1024  # 1 MiB
# Bound the wait for the engine to move a transfer out of INITIALIZING.
_TRANSFER_READY_TIMEOUT = 120  # seconds


def _normalise_uuid(raw: str) -> str:
    """Lowercase, strip dashes — same normalisation discovery applies to vm.id."""
    return (raw or "").replace("-", "").lower()


def _ovirt_url(hv: Hypervisor) -> str:
    cfg = hv.connection_config or {}
    host = hv.host or "localhost"
    api_path = cfg.get("api_path") or "/ovirt-engine/api"
    port = f":{hv.port}" if hv.port else ""
    return f"https://{host}{port}{api_path}"


def _connect(hv: Hypervisor):
    """Open an oVirt SDK Connection — mirrors ``discovery._discover_ovirt``."""
    try:
        import ovirtsdk4 as sdk  # type: ignore
    except ImportError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND",
            "ovirt-engine-sdk-python not installed in worker image",
            cause=e,
        ) from e

    cfg = hv.connection_config or {}
    ca_file = cfg.get("ca_file") or hv.ssl_cert_path or None
    password = hv.password_plain
    if not password:
        raise ConversionError(
            "ERR_HV_CREDENTIALS_MISSING",
            f"No usable credential for oVirt engine {hv.host}",
        )
    try:
        return sdk.Connection(
            url=_ovirt_url(hv),
            username=hv.username or "admin@internal",
            password=password,
            ca_file=ca_file,
            insecure=not bool(hv.verify_ssl),
            timeout=60,
        )
    except Exception as e:  # NOSONAR — SDK raises various types
        raise ConversionError(
            "ERR_HV_AUTH_FAILED",
            f"oVirt connection to {hv.host} failed: {e}",
            cause=e,
        ) from e


def _resolve_vm(connection, vm: VirtualMachine):
    """Return the SDK VM object matching ``vm`` (by uuid, then name)."""
    vms_service = connection.system_service().vms_service()
    try:
        ovirt_vms = vms_service.list()
    except Exception as e:  # NOSONAR
        raise ConversionError(
            "ERR_HV_UNREACHABLE",
            f"could not list oVirt VMs: {e}",
            cause=e,
        ) from e

    if vm.source_uuid:
        want = _normalise_uuid(vm.source_uuid)
        for o in ovirt_vms:
            if _normalise_uuid(getattr(o, "id", "")) == want:
                return o
    for o in ovirt_vms:
        if getattr(o, "name", None) == vm.name:
            return o
    raise ConversionError(
        "ERR_VM_NOT_FOUND",
        f"VM {vm.name!r} (uuid={vm.source_uuid}) not found on oVirt engine",
    )


def _disk_source_format(disk) -> SourceFormat:
    """Map an oVirt ``DiskFormat`` to our ``SourceFormat`` (COW -> qcow2)."""
    fmt = getattr(getattr(disk, "format", None), "value", None) or str(
        getattr(disk, "format", "") or ""
    )
    return SourceFormat.QCOW2 if "cow" in fmt.lower() else SourceFormat.RAW


class OvirtPuller:
    """:class:`DiskPuller` for oVirt/RHV via the ImageTransfer download API."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        connection = _connect(hv)
        try:
            o_vm = _resolve_vm(connection, vm)
            system = connection.system_service()
            disks_service = system.disks_service()
            vm_service = system.vms_service().vm_service(o_vm.id)
            try:
                attachments = vm_service.disk_attachments_service().list() or []
            except Exception as e:  # NOSONAR
                raise ConversionError(
                    "ERR_DISK_NOT_FOUND",
                    f"could not list disk attachments for VM {vm.name!r}: {e}",
                    cause=e,
                ) from e

            descriptors: list[DiskDescriptor] = []
            index = 0
            for att in attachments:
                if not att.disk or not att.disk.id:
                    continue
                try:
                    disk = disks_service.disk_service(att.disk.id).get()
                except Exception:  # NOSONAR — skip a disk that cannot be read
                    logger.warning("oVirt: could not read disk %s", att.disk.id)
                    continue
                size = int(
                    getattr(disk, "provisioned_size", 0)
                    or getattr(disk, "total_size", 0)
                    or 0
                )
                descriptors.append(
                    DiskDescriptor(
                        disk_index=index,
                        source_format=_disk_source_format(disk),
                        size_bytes=size,
                        locator=str(disk.id),
                    )
                )
                index += 1
            if not descriptors:
                raise ConversionError(
                    "ERR_DISK_NOT_FOUND",
                    f"VM {vm.name!r}: no disks discovered on oVirt",
                )
            return descriptors
        finally:
            _close(connection)

    def pull_disk(
        self,
        hv: Hypervisor,
        vm: VirtualMachine,
        descriptor: DiskDescriptor,
        dest_path: Path,
        *,
        cold: bool = True,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> PullResult:
        # ImageTransfer download requires the disk to be in OK state; oVirt
        # supports downloading a running VM's disk via a snapshot, but we keep
        # the conservative cold contract (caller powers the VM off).
        if not cold:
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "Live download not implemented for oVirt; power VM off first",
            )
        connection = _connect(hv)
        try:
            sha256 = self._download_disk(
                connection,
                disk_id=descriptor.locator,
                dest_path=dest_path,
                expected_size=descriptor.size_bytes,
                hv=hv,
                progress_cb=progress_cb,
            )
        finally:
            _close(connection)
        return PullResult(
            staged_path=dest_path,
            source_format=descriptor.source_format,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    def convert_on_source(
        self,
        hv: Hypervisor,
        vm: VirtualMachine,
        descriptor: DiskDescriptor,
        dest_path: Path,
        *,
        target_format: str = "qcow2",
        cold: bool = True,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> PullResult:
        """Download the disk to the worker, then compress locally with qemu-img.

        oVirt has no single SSH node to run ``qemu-img`` on (the data lives on
        SDS/host storage reached through the engine), so the disk is streamed to
        the worker scratch via ImageTransfer and compressed locally — only the
        small qcow2 then crosses the slow uplink in the SFTP bridge.
        """
        if not cold:
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "Live download not implemented for oVirt; power VM off first",
            )
        raw_tmp = dest_path.with_suffix(dest_path.suffix + ".download")
        connection = _connect(hv)
        try:
            self._download_disk(
                connection,
                disk_id=descriptor.locator,
                dest_path=raw_tmp,
                expected_size=descriptor.size_bytes,
                hv=hv,
                progress_cb=progress_cb,
            )
        finally:
            _close(connection)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        try:
            local_qemu_img_convert(raw_tmp, partial, target_format)
            partial.replace(dest_path)
        except ConversionError:
            partial.unlink(missing_ok=True)
            raise
        finally:
            raw_tmp.unlink(missing_ok=True)

        sha256 = sha256_file(dest_path)
        out_fmt = SourceFormat.QCOW2 if target_format == "qcow2" else SourceFormat.RAW
        return PullResult(
            staged_path=dest_path,
            source_format=out_fmt,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    # --- internal helpers ---------------------------------------------------

    @classmethod
    def _download_disk(
        cls,
        connection,
        *,
        disk_id: str,
        dest_path: Path,
        expected_size: int,
        hv: Hypervisor,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        """Run a full ImageTransfer download of ``disk_id`` into ``dest_path``."""
        import ovirtsdk4.types as types  # type: ignore

        system = connection.system_service()
        transfers_service = system.image_transfers_service()
        try:
            transfer = transfers_service.add(
                types.ImageTransfer(
                    disk=types.Disk(id=disk_id),
                    direction=types.ImageTransferDirection.DOWNLOAD,
                )
            )
        except Exception as e:  # NOSONAR
            raise ConversionError(
                "ERR_HV_UNREACHABLE",
                f"oVirt: could not start image transfer for disk {disk_id}: {e}",
                cause=e,
            ) from e

        transfer_service = transfers_service.image_transfer_service(transfer.id)
        try:
            url = cls._await_transfer_url(transfer_service, types)
            return cls._stream_url(
                url,
                dest_path=dest_path,
                expected_size=expected_size,
                hv=hv,
                progress_cb=progress_cb,
            )
        finally:
            try:
                transfer_service.finalize()
            except Exception:  # NOSONAR — finalize failure must not mask result
                logger.debug("oVirt: transfer finalize failed", exc_info=True)

    @staticmethod
    def _await_transfer_url(transfer_service, types) -> str:
        """Poll until the transfer leaves INITIALIZING and return its URL."""
        deadline = time.monotonic() + _TRANSFER_READY_TIMEOUT
        transfer = transfer_service.get()
        while transfer.phase == types.ImageTransferPhase.INITIALIZING:
            if time.monotonic() >= deadline:
                raise ConversionError(
                    "ERR_HV_TRANSIENT",
                    "oVirt image transfer stuck in INITIALIZING",
                )
            time.sleep(1)
            transfer = transfer_service.get()
        url = getattr(transfer, "proxy_url", None) or getattr(transfer, "transfer_url", None)
        if not url:
            raise ConversionError(
                "ERR_HV_UNREACHABLE",
                "oVirt image transfer exposed no proxy_url/transfer_url",
            )
        return url

    @staticmethod
    def _stream_url(
        url: str,
        *,
        dest_path: Path,
        expected_size: int,
        hv: Hypervisor,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        import hashlib

        import requests  # type: ignore

        cfg = hv.connection_config or {}
        ca_file = cfg.get("ca_file") or hv.ssl_cert_path or None
        verify: object = ca_file if (hv.verify_ssl and ca_file) else bool(hv.verify_ssl)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        h = hashlib.sha256()
        bytes_done = 0
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # insecure-TLS warning is intentional in dev
                with requests.get(url, stream=True, verify=verify, timeout=(30, 600)) as resp:
                    resp.raise_for_status()
                    with open(partial, "wb") as fout:
                        for chunk in resp.iter_content(chunk_size=_HASH_CHUNK):
                            if not chunk:
                                continue
                            fout.write(chunk)
                            h.update(chunk)
                            bytes_done += len(chunk)
                            if progress_cb is not None:
                                try:
                                    progress_cb(bytes_done, expected_size or bytes_done)
                                except Exception:  # NOSONAR
                                    logger.debug("progress_cb raised", exc_info=True)
            partial.replace(dest_path)
        except Exception as e:  # NOSONAR
            partial.unlink(missing_ok=True)
            raise ConversionError(
                "ERR_NETWORK_TIMEOUT",
                f"oVirt image download from {hv.host} failed: {e}",
                cause=e,
            ) from e
        return h.hexdigest()


def _close(connection) -> None:
    try:
        connection.close()
    except Exception:  # NOSONAR — best-effort close
        logger.debug("oVirt: connection close failed", exc_info=True)


# Structural conformance check (Protocol) — kept explicit for readers.
_: DiskPuller = OvirtPuller()
