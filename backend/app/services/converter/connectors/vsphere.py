"""
vSphere / ESXi connector — best-effort (no test environment available).

Broadcom ended free ESXi in Feb 2024, so this connector cannot be validated
against a live vCenter/ESXi here. It is implemented against documented pyVmomi +
datastore HTTP (``/folder``) behaviour and is covered only by mocked unit tests.

Strategy (cold pull):
1. ``pyVmomi`` ``SmartConnect`` to vCenter/ESXi.
2. Resolve the VM by ``source_uuid`` (instanceUuid / BIOS uuid, normalised) or
   name; enumerate ``VirtualDisk`` devices (backing fileName + capacity).
3. Download the disk's **flat extent** via the datastore ``/folder`` HTTP API
   using the SOAP session cookie, streaming to the destination as RAW.
4. The in-cluster qemu-img Job (or local qemu-img for the SFTP bridge) converts
   the RAW image to qcow2.

**Limitation:** only flat-backed disks (``monolithicFlat`` / thick eager/lazy
zeroed, i.e. a single ``-flat.vmdk`` extent that is raw on the wire) are
supported by the HTTP path. Thin / ``vmfssparse`` / ``seSparse`` disks must be
migrated with ``virt-v2v`` (VDDK), which is out of scope for this HTTP bridge.
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

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


def _normalise_uuid(raw: str) -> str:
    return (raw or "").replace("-", "").lower()


def _flat_extent_path(descriptor_path: str) -> str:
    """``[ds] folder/disk.vmdk`` -> ``[ds] folder/disk-flat.vmdk``.

    Already-``-flat`` paths are returned unchanged. The flat extent of a
    thick/monolithicFlat VMDK is raw data of the disk's capacity, which
    qemu-img reads as RAW.
    """
    if descriptor_path.endswith("-flat.vmdk"):
        return descriptor_path
    if descriptor_path.endswith(".vmdk"):
        return descriptor_path[: -len(".vmdk")] + "-flat.vmdk"
    return descriptor_path


def _split_ds_path(ds_path: str) -> tuple[str, str]:
    """``[datastore1] folder/disk-flat.vmdk`` -> ('datastore1', 'folder/disk-flat.vmdk')."""
    if not ds_path.startswith("["):
        raise ConversionError(
            "ERR_DISK_NOT_FOUND", f"unexpected datastore path: {ds_path!r}",
        )
    close = ds_path.find("]")
    if close < 0:
        raise ConversionError(
            "ERR_DISK_NOT_FOUND", f"unexpected datastore path: {ds_path!r}",
        )
    datastore = ds_path[1:close].strip()
    rel = ds_path[close + 1:].strip()
    return datastore, rel


def _connect(hv: Hypervisor):
    try:
        from pyVim.connect import SmartConnect  # type: ignore
    except ImportError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND",
            "pyvmomi not installed in worker image",
            cause=e,
        ) from e
    password = hv.password_plain
    if not password:
        raise ConversionError(
            "ERR_HV_CREDENTIALS_MISSING",
            f"No usable credential for vSphere endpoint {hv.host}",
        )
    if hv.verify_ssl:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl._create_unverified_context()  # NOSONAR — self-signed dev clusters
    try:
        return SmartConnect(
            host=hv.host,
            user=hv.username,
            pwd=password,
            port=hv.port or 443,
            sslContext=ctx,
        )
    except Exception as e:  # NOSONAR — pyVmomi raises various types
        raise ConversionError(
            "ERR_HV_AUTH_FAILED",
            f"vSphere connection to {hv.host} failed: {e}",
            cause=e,
        ) from e


def _disconnect(si) -> None:
    try:
        from pyVim.connect import Disconnect  # type: ignore

        Disconnect(si)
    except Exception:  # NOSONAR — best-effort
        logger.debug("vSphere disconnect failed", exc_info=True)


def _all_vms(si):
    content = si.RetrieveContent()
    from pyVmomi import vim  # type: ignore

    view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True,
    )
    try:
        return list(view.view)
    finally:
        try:
            view.Destroy()
        except Exception:  # NOSONAR
            logger.debug("vSphere view destroy failed", exc_info=True)


def _resolve_vm(si, vm: VirtualMachine):
    want = _normalise_uuid(vm.source_uuid) if vm.source_uuid else None
    candidates = _all_vms(si)
    if want:
        for o in candidates:
            cfg = getattr(o, "config", None)
            uuids = {
                _normalise_uuid(getattr(cfg, "instanceUuid", "") or ""),
                _normalise_uuid(getattr(cfg, "uuid", "") or ""),
            }
            if want in uuids:
                return o
    for o in candidates:
        if getattr(o, "name", None) == vm.name:
            return o
    raise ConversionError(
        "ERR_VM_NOT_FOUND",
        f"VM {vm.name!r} (uuid={vm.source_uuid}) not found on vSphere endpoint",
    )


def _datacenter_name(vm_obj) -> str:
    """Walk the inventory parent chain up to the enclosing Datacenter name."""
    from pyVmomi import vim  # type: ignore

    node = getattr(vm_obj, "parent", None)
    while node is not None:
        if isinstance(node, vim.Datacenter):
            return node.name
        node = getattr(node, "parent", None)
    raise ConversionError(
        "ERR_VM_NOT_FOUND", f"could not resolve datacenter for VM {vm_obj.name!r}",
    )


def _virtual_disks(vm_obj):
    from pyVmomi import vim  # type: ignore

    hw = getattr(getattr(vm_obj, "config", None), "hardware", None)
    devices = getattr(hw, "device", []) or []
    return [d for d in devices if isinstance(d, vim.vm.device.VirtualDisk)]


def _is_flat_backing(backing) -> bool:
    """True only for a single flat extent (``FlatVer2BackingInfo``).

    A thin **and** a thick base disk are both ``FlatVer2`` (thin only flips
    ``thinProvisioned``); the datastore ``/folder`` HTTP path serves their
    ``-flat.vmdk`` as readable RAW. Snapshots / linked clones use
    ``SeSparseBackingInfo`` / ``SparseVer2BackingInfo``, whose active delta is
    NOT a flat extent — the HTTP path cannot read it, so those are rejected
    upfront with an actionable error rather than a corrupt pull.
    """
    from pyVmomi import vim  # type: ignore

    return isinstance(backing, vim.vm.device.VirtualDisk.FlatVer2BackingInfo)


class VsphereStubPuller:
    """:class:`DiskPuller` for vSphere/ESXi — best-effort HTTP datastore download."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        si = _connect(hv)
        try:
            vm_obj = _resolve_vm(si, vm)
            disks = _virtual_disks(vm_obj)
            descriptors: list[DiskDescriptor] = []
            for index, dev in enumerate(disks):
                backing = getattr(dev, "backing", None)
                file_name = getattr(backing, "fileName", None)
                if not file_name:
                    continue
                if not _is_flat_backing(backing):
                    raise ConversionError(
                        "ERR_DISK_NOT_FOUND",
                        f"VM {vm.name!r} disk {index} has a non-flat backing "
                        f"({type(backing).__name__}) — likely a snapshot/linked "
                        "clone. Consolidate snapshots on the VM, then retry.",
                    )
                capacity = int(
                    getattr(dev, "capacityInBytes", 0)
                    or (getattr(dev, "capacityInKB", 0) or 0) * 1024
                )
                descriptors.append(
                    DiskDescriptor(
                        disk_index=index,
                        # Downloaded as the raw flat extent.
                        source_format=SourceFormat.RAW,
                        size_bytes=capacity,
                        locator=str(file_name),
                    )
                )
            if not descriptors:
                raise ConversionError(
                    "ERR_DISK_NOT_FOUND",
                    f"VM {vm.name!r}: no virtual disks discovered on vSphere",
                )
            return descriptors
        finally:
            _disconnect(si)

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
        if not cold:
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "Live pull not implemented for vSphere; power VM off first",
            )
        si = _connect(hv)
        try:
            vm_obj = _resolve_vm(si, vm)
            stopped_here = self._power_off_if_running(vm_obj)
            try:
                sha256 = self._download_flat(
                    si, vm_obj, descriptor.locator, dest_path,
                    descriptor.size_bytes, hv, progress_cb,
                )
            finally:
                if stopped_here:
                    self._power_on_best_effort(vm_obj)
        finally:
            _disconnect(si)
        return PullResult(
            staged_path=dest_path,
            source_format=SourceFormat.RAW,
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
        """Download the flat extent then compress locally with qemu-img."""
        if not cold:
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "Live pull not implemented for vSphere; power VM off first",
            )
        raw_tmp = dest_path.with_suffix(dest_path.suffix + ".raw")
        si = _connect(hv)
        try:
            vm_obj = _resolve_vm(si, vm)
            stopped_here = self._power_off_if_running(vm_obj)
            try:
                self._download_flat(
                    si, vm_obj, descriptor.locator, raw_tmp,
                    descriptor.size_bytes, hv, progress_cb,
                )
            finally:
                if stopped_here:
                    self._power_on_best_effort(vm_obj)
        finally:
            _disconnect(si)

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

    @staticmethod
    def _power_off_if_running(vm_obj) -> bool:
        state = getattr(getattr(vm_obj, "runtime", None), "powerState", None)
        if str(state) != "poweredOn":
            return False
        try:
            task = vm_obj.PowerOffVM_Task()
        except Exception as e:  # NOSONAR — pyVmomi raises various SOAP faults
            # Free / evaluation ESXi licenses make the vSphere API read-only, so
            # PowerOffVM_Task raises vim.fault.RestrictedVersion. A running VM's
            # -flat.vmdk is also locked and cannot be pulled. Surface a clear,
            # actionable error instead of a cryptic ERR_INTERNAL.
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                f"VM {getattr(vm_obj, 'name', '?')!r} is powered on and the ESXi "
                "API refused to stop it (free/evaluation ESXi licenses make the "
                "vSphere API read-only). Power the VM off manually in the ESXi "
                "console, then retry the migration.",
                cause=e,
            ) from e
        _wait_task(task)
        return True

    @staticmethod
    def _power_on_best_effort(vm_obj) -> None:
        try:
            _wait_task(vm_obj.PowerOnVM_Task())
        except Exception:  # NOSONAR — restart failure must not mask result
            logger.warning("could not power vSphere VM %s back on", vm_obj.name)

    @classmethod
    def _download_flat(
        cls,
        si,
        vm_obj,
        descriptor_path: str,
        dest_path: Path,
        expected_size: int,
        hv: Hypervisor,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        import hashlib

        import requests  # type: ignore

        datastore, rel = _split_ds_path(_flat_extent_path(descriptor_path))
        dc = _datacenter_name(vm_obj)
        url = (
            f"https://{hv.host}:{hv.port or 443}/folder/{quote(rel)}"
            f"?dcPath={quote(dc)}&dsName={quote(datastore)}"
        )
        cookie = si._stub.cookie  # SOAP session cookie authorises the /folder GET
        verify = bool(hv.verify_ssl)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        h = hashlib.sha256()
        bytes_done = 0
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with requests.get(
                    url, stream=True, verify=verify,
                    headers={"Cookie": cookie}, timeout=(30, 600),
                ) as resp:
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
                f"vSphere datastore download from {hv.host} failed: {e}",
                cause=e,
            ) from e
        return h.hexdigest()


def _wait_task(task, timeout: int = 600) -> None:
    """Block until a pyVmomi task finishes; raise on failure."""
    import time

    from pyVmomi import vim  # type: ignore

    deadline = time.monotonic() + timeout
    while task.info.state not in (vim.TaskInfo.State.success, vim.TaskInfo.State.error):
        if time.monotonic() >= deadline:
            raise ConversionError("ERR_HV_TRANSIENT", "vSphere task timed out")
        time.sleep(2)
    if task.info.state == vim.TaskInfo.State.error:
        msg = getattr(getattr(task.info, "error", None), "msg", "unknown")
        raise ConversionError("ERR_HV_UNREACHABLE", f"vSphere task failed: {msg}")


# Structural conformance check (Protocol) — kept explicit for readers.
_: DiskPuller = VsphereStubPuller()
