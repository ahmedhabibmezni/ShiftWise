"""
VMware Workstation connector — read a VM's VMDK from the local Workstation host.

Topology
--------
VMware Workstation is a desktop product: the disk files live on the same host
that runs Workstation, and the ShiftWise worker runs there too (laptop control
plane). The cluster NFS is **not** reachable from that host except via the
bastion-jump SFTP bridge (same constraint as the Proxmox-on-laptop path). So the
only viable migration path mirrors the Proxmox convert-on-source bridge:

1. ``list_disks``        — parse the persisted ``.vmx`` for disk descriptors.
2. ``convert_on_source`` — run ``qemu-img convert -O qcow2 -c`` **locally** on
   the worker host (the VMDK is local), powering the VM off first for a cold,
   crash-consistent read; the small qcow2 is then uploaded to the cluster NFS by
   ``ConverterService._source_convert_sftp`` over the bastion jump.
3. ``pull_disk``         — local stream-copy of the VMDK, for a worker that
   *does* share the destination filesystem (in-cluster / shared-mount staging).

The VMX path is captured at discovery time and stored on
``VirtualMachine.custom_metadata["vmx_path"]`` (see ``services/discovery.py``).
A monolithic disk is a single ``.vmdk``; a split disk is a small descriptor
``.vmdk`` plus ``-flat`` / ``-s00x`` extents. ``qemu-img`` follows the extents
automatically from the descriptor, so the locator is the descriptor path.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)

logger = logging.getLogger(__name__)


# A VMX disk device key: a bus name + controller index, a colon, then the unit
# index — e.g. ``scsi0:0``, ``sata0:1``, ``nvme0:0``, ``ide1:0``. The trailing
# ``.filename`` sub-key names the backing file. Matching the device prefix (not a
# plain ``startswith``) keeps controller/feature keys (``scsi0.present``,
# ``scsi0.virtualdev``) out of the disk set.
_DISK_DEV_RE = re.compile(r"^(?:scsi|sata|nvme|ide)\d+:\d+$")

_HASH_CHUNK = 1024 * 1024  # 1 MiB


def _vmx_path_for(vm: VirtualMachine) -> str:
    """Return the absolute ``.vmx`` path captured at discovery, or raise.

    Discovery stores it on ``custom_metadata["vmx_path"]``. A VM discovered by
    an older build (or by a non-Workstation connector) lacks it — re-running
    discovery on the Workstation hypervisor repopulates it.
    """
    meta = vm.custom_metadata or {}
    vmx_path = meta.get("vmx_path") if isinstance(meta, dict) else None
    if not vmx_path:
        raise ConversionError(
            "ERR_DISK_NOT_FOUND",
            f"VM {vm.name!r} has no recorded vmx_path; re-run discovery on the "
            "VMware Workstation hypervisor before migrating",
        )
    if not os.path.isfile(vmx_path):
        raise ConversionError(
            "ERR_DISK_NOT_FOUND",
            f"VMX file not found on the worker host: {vmx_path}",
        )
    return vmx_path


def _parse_vmx_file(vmx_path: str) -> dict[str, str]:
    """Parse a ``.vmx`` into a flat lowercased key→value dict.

    Self-contained (does not import the discovery service) so the converter
    package has no dependency on the discovery package.
    """
    try:
        with open(vmx_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as e:
        raise ConversionError(
            "ERR_SOURCE_CORRUPT",
            f"could not read VMX {vmx_path}: {e}",
            cause=e,
        ) from e
    config: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        config[key.strip().lower()] = value.strip().strip('"')
    return config


def _vmdk_disk_size(descriptor_path: Path) -> int:
    """Best-effort on-disk byte size of a VMDK disk set (descriptor + extents).

    Sums the descriptor file and any sibling ``<base>-*.vmdk`` extents. Used for
    NFS free-space pre-checks and progress totals — not for virtual sizing.
    """
    directory = descriptor_path.parent
    base = descriptor_path.stem  # filename without ``.vmdk``
    total = 0
    try:
        for entry in os.listdir(directory):
            low = entry.lower()
            if not low.endswith(".vmdk"):
                continue
            stem = entry[: -len(".vmdk")]
            if stem == base or stem.startswith(base + "-"):
                try:
                    total += os.path.getsize(directory / entry)
                except OSError:
                    continue
    except OSError:
        logger.debug("could not list %s for VMDK sizing", directory, exc_info=True)
    return total


def _extract_disk_files(vmx_path: str, config: dict[str, str]) -> list[tuple[str, str]]:
    """Return ``[(device, absolute_vmdk_path), ...]`` for real disks, stable-sorted.

    A real disk is a ``<device>.filename`` whose value ends in ``.vmdk``, is not
    a cdrom (``<device>.devicetype`` containing ``cdrom``), and is not explicitly
    absent (``<device>.present = "FALSE"``).
    """
    vmx_dir = os.path.dirname(os.path.abspath(vmx_path))
    disks: list[tuple[str, str]] = []
    for key, value in config.items():
        if not key.endswith(".filename"):
            continue
        device = key[: -len(".filename")]
        if not _DISK_DEV_RE.match(device):
            continue
        if not value.lower().endswith(".vmdk"):
            continue
        if config.get(f"{device}.present", "true").lower() == "false":
            continue
        if "cdrom" in config.get(f"{device}.devicetype", "").lower():
            continue
        path = value if os.path.isabs(value) else os.path.join(vmx_dir, value)
        disks.append((device, os.path.normpath(path)))
    disks.sort(key=lambda t: t[0])
    return disks


def _is_running(vmx_path: str) -> bool:
    """True if Workstation reports ``vmx_path`` as a running VM (``vmrun list``)."""
    from app.services.discovery import _find_vmrun, _get_running_vmx_paths

    def _norm(p: str) -> str:
        return p.replace("\\", "/").lower()

    try:
        running = _get_running_vmx_paths(_find_vmrun())
    except Exception:  # NOSONAR — if vmrun is unavailable, assume not running
        logger.debug("vmrun list failed; assuming VM not running", exc_info=True)
        return False
    return _norm(vmx_path) in {_norm(p) for p in running}


def _vmrun(*args: str, timeout: int = 120) -> None:
    """Run a ``vmrun -T ws`` command, raising ConversionError on failure."""
    from app.services.discovery import _find_vmrun, _run_vmrun

    try:
        _run_vmrun(_find_vmrun(), "-T", "ws", *args, timeout=timeout)
    except Exception as e:  # NOSONAR — discovery raises DiscoveryError variants
        raise ConversionError(
            "ERR_HV_UNREACHABLE",
            f"vmrun {' '.join(args)} failed: {e}",
            cause=e,
        ) from e


def _stop_vm_cold(vmx_path: str) -> None:
    """Power the VM off for a crash-consistent read: soft first, then hard.

    A ``soft`` stop is an ACPI shutdown that needs VMware Tools cooperation in
    the guest; guests without responsive tools (e.g. a Proxmox/Debian appliance)
    never acknowledge it and ``vmrun`` blocks until timeout. So we attempt a
    short graceful soft stop and fall back to ``hard`` (immediate power-off,
    the analog of Proxmox ``qm stop`` used by the proven Proxmox bridge — a
    journaled guest filesystem recovers cleanly on next boot).
    """
    try:
        _vmrun("stop", vmx_path, "soft", timeout=30)
        return
    except ConversionError:
        logger.info("soft stop did not complete; forcing hard power-off: %s", vmx_path)
    _vmrun("stop", vmx_path, "hard", timeout=60)


class VmwareWorkstationPuller:
    """:class:`DiskPuller` for VMware Workstation (local-host disk access)."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        vmx_path = _vmx_path_for(vm)
        config = _parse_vmx_file(vmx_path)
        disk_files = _extract_disk_files(vmx_path, config)
        if not disk_files:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"no VMDK disks found in {vmx_path}",
            )
        descriptors: list[DiskDescriptor] = []
        for index, (_device, vmdk_path) in enumerate(disk_files):
            descriptors.append(
                DiskDescriptor(
                    disk_index=index,
                    source_format=SourceFormat.VMDK,
                    size_bytes=_vmdk_disk_size(Path(vmdk_path)),
                    locator=vmdk_path,
                )
            )
        return descriptors

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
        """Stream-copy the VMDK disk set to ``dest_path`` (shared-mount worker).

        For a monolithic disk this copies the single ``.vmdk``; for a split disk
        the descriptor alone is not self-contained, so callers on the laptop
        topology must use :meth:`convert_on_source` instead (it resolves extents
        through ``qemu-img``). Raises if the source is a non-monolithic VMDK that
        cannot be copied as a single file.
        """
        if not cold and _is_running(_vmx_path_for(vm)):
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "live pull not supported for VMware Workstation; power VM off first",
            )
        src = Path(descriptor.locator)
        if not src.is_file():
            raise ConversionError(
                "ERR_DISK_NOT_FOUND", f"VMDK not found: {src}",
            )
        # A split disk has sibling extents the descriptor references by name; a
        # single-file copy would lose the data. Detect and route to convert.
        if _vmdk_disk_size(src) > src.stat().st_size + _HASH_CHUNK:
            raise ConversionError(
                "ERR_UNSUPPORTED_FORMAT",
                "split VMDK detected; enable CONVERTER_SOURCE_CONVERT_SFTP so the "
                "worker converts on-source (qemu-img resolves the extents)",
            )
        sha256 = self._stream_copy(src, dest_path, descriptor.size_bytes, progress_cb)
        return PullResult(
            staged_path=dest_path,
            source_format=SourceFormat.VMDK,
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
        """Convert+compress the VMDK to ``dest_path`` locally via ``qemu-img``.

        Mirrors :meth:`ProxmoxPuller.convert_on_source` but runs on the worker
        host (the VMDK is local). For a cold migration the VM is powered off
        before the read so the guest filesystem is quiescent, then restarted.
        ``qemu-img convert -c`` follows VMDK extents and sparse-compresses the
        output, so only the small qcow2 crosses the slow uplink afterwards.
        """
        vmx_path = _vmx_path_for(vm)
        src = Path(descriptor.locator)
        if not src.is_file():
            raise ConversionError(
                "ERR_DISK_NOT_FOUND", f"VMDK not found: {src}",
            )

        stopped_here = False
        if cold and _is_running(vmx_path):
            _stop_vm_cold(vmx_path)
            stopped_here = True

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        try:
            self._run_qemu_img_convert(src, partial, target_format)
            partial.replace(dest_path)
        except ConversionError:
            partial.unlink(missing_ok=True)
            raise
        finally:
            if stopped_here:
                try:
                    _vmrun("start", vmx_path, "nogui")
                except ConversionError:  # NOSONAR — restart failure must not mask result
                    logger.warning("could not restart source VM after convert: %s", vmx_path)

        sha256 = self._sha256(dest_path, progress_cb)
        out_fmt = SourceFormat.QCOW2 if target_format == "qcow2" else SourceFormat.RAW
        return PullResult(
            staged_path=dest_path,
            source_format=out_fmt,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    # --- internal helpers ---------------------------------------------------

    @staticmethod
    def _run_qemu_img_convert(src: Path, dest: Path, target_format: str) -> None:
        qemu_img = settings.CONVERTER_LOCAL_QEMU_IMG
        cmd = [
            qemu_img, "convert", "-p", "-O", target_format, "-c",
            str(src), str(dest),
        ]
        logger.info("qemu-img convert: %s -> %s (%s)", src, dest, target_format)
        try:
            result = subprocess.run(  # NOSONAR — local trusted tool, fixed argv
                cmd,
                capture_output=True,
                text=True,
                timeout=6 * 3600,
                check=False,
            )
        except FileNotFoundError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                f"qemu-img not found at {qemu_img!r}; set CONVERTER_LOCAL_QEMU_IMG",
                cause=e,
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ConversionError(
                "ERR_NETWORK_TIMEOUT",
                f"qemu-img convert timed out for {src}",
                cause=e,
            ) from e
        if result.returncode != 0:
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"qemu-img convert failed (rc={result.returncode}): "
                f"{(result.stderr or result.stdout or 'no output').strip()}",
            )

    @staticmethod
    def _stream_copy(
        src: Path,
        dest: Path,
        expected_size: int,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_suffix(dest.suffix + ".partial")
        h = hashlib.sha256()
        done = 0
        try:
            with open(src, "rb") as fin, open(partial, "wb") as fout:
                while True:
                    buf = fin.read(_HASH_CHUNK)
                    if not buf:
                        break
                    fout.write(buf)
                    h.update(buf)
                    done += len(buf)
                    if progress_cb is not None:
                        try:
                            progress_cb(done, expected_size or done)
                        except Exception:  # NOSONAR — callback must never abort copy
                            logger.debug("progress_cb raised", exc_info=True)
            partial.replace(dest)
        except OSError as e:
            partial.unlink(missing_ok=True)
            raise ConversionError(
                "ERR_INTERNAL", f"VMDK copy failed: {e}", cause=e,
            ) from e
        return h.hexdigest()

    @staticmethod
    def _sha256(path: Path, progress_cb: Optional[ProgressCallback]) -> str:
        h = hashlib.sha256()
        total = path.stat().st_size
        done = 0
        with open(path, "rb") as fin:
            while True:
                buf = fin.read(_HASH_CHUNK)
                if not buf:
                    break
                h.update(buf)
                done += len(buf)
                if progress_cb is not None:
                    try:
                        progress_cb(done, total or done)
                    except Exception:  # NOSONAR — callback must never abort hashing
                        logger.debug("progress_cb raised", exc_info=True)
        return h.hexdigest()


# Structural conformance check (Protocol) — kept explicit for readers.
_: DiskPuller = VmwareWorkstationPuller()
