"""
Physical server (P2V) connector — capture each block device of a bare-metal
Linux host as a raw stream over SSH.

Strategy (POSIX-minimal source — dd/gzip/ssh only):
  list_disks       : read the per-disk plan captured at discovery time.
  pull_disk        : ``dd if=<dev> bs=4M | gzip -1`` on the source, stream the
                     gzip over the SSH channel, gunzip into a staged .raw on
                     NFS. (implemented in a later task)
  convert_on_source: dev SFTP-bridge path. (implemented in a later task)
"""

from __future__ import annotations

import hashlib
import logging
import shlex
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import List, Optional

from app.core.ssh import apply_host_key_policy
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

_PLAN_KEY = "physical_disks"


def build_capture_command(device: str) -> str:
    """Return the remote shell command that streams a gzipped raw disk.

    ``conv=noerror,sync`` keeps the stream length stable on a read error; the
    free-space regions compress away, so only used blocks cross the wire.
    """
    safe_dev = shlex.quote(device)
    return f"dd if={safe_dev} bs=4M conv=noerror,sync 2>/dev/null | gzip -1"


def _disk_plan(vm: VirtualMachine) -> list[dict]:
    meta = getattr(vm, "custom_metadata", None) or {}
    return list(meta.get(_PLAN_KEY) or [])


def _stream_gunzip_to_file(
    channel,
    dest_path: Path,
    *,
    expected_size: int,
    progress_cb: Optional[ProgressCallback],
    chunk: int = 1024 * 1024,
) -> str:
    """Decompress a gzip byte-stream from ``channel`` into ``dest_path``.

    Returns the sha256 of the *decompressed* (raw) bytes. ``channel`` only needs
    a ``read(n) -> bytes`` method (paramiko ChannelFile or a test fake).
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    partial = dest_path.with_suffix(dest_path.suffix + ".partial")
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)  # 16 = gzip header
    h = hashlib.sha256()
    written = 0
    try:
        with open(partial, "wb") as fout:
            while True:
                buf = channel.read(chunk)
                if not buf:
                    break
                raw = decompressor.decompress(buf)
                if raw:
                    fout.write(raw)
                    h.update(raw)
                    written += len(raw)
                    if progress_cb is not None:
                        try:
                            progress_cb(written, expected_size or written)
                        except Exception:  # NOSONAR — progress is best-effort
                            logger.debug("progress_cb raised", exc_info=True)
            tail = decompressor.flush()
            if tail:
                fout.write(tail)
                h.update(tail)
        partial.replace(dest_path)
    except Exception as e:  # NOSONAR — normalise to ConversionError
        partial.unlink(missing_ok=True)
        raise ConversionError(
            "ERR_NETWORK_TIMEOUT",
            f"physical capture stream failed for {dest_path.name}: {e}",
            cause=e,
        ) from e
    return h.hexdigest()


def _sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _local_raw_to_qcow2(raw_path: Path, out_path: Path) -> None:
    """Convert a local staged ``.raw`` into a compressed sparse qcow2."""
    if shutil.which("qemu-img") is None:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND", "qemu-img not found in worker image",
        )
    cmd = [
        "qemu-img", "convert", "-O", "qcow2", "-c",
        str(raw_path), str(out_path),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise ConversionError(
            "ERR_OUTPUT_INVALID",
            f"qemu-img convert failed (rc={result.returncode}): {result.stderr}",
        )
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise ConversionError("ERR_OUTPUT_INVALID", "qemu-img produced no output")


def _ssh_connect(hv: Hypervisor):
    try:
        import paramiko  # type: ignore
    except ImportError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND", "paramiko not installed in worker image", cause=e,
        ) from e
    ssh = paramiko.SSHClient()
    apply_host_key_policy(ssh)  # Audit H-02
    try:
        ssh.connect(
            hostname=hv.host,
            port=hv.port or 22,
            username=hv.username,
            password=hv.password_plain or None,
            timeout=15,
            look_for_keys=True,
        )
    except Exception as e:  # NOSONAR
        raise ConversionError(
            "ERR_HV_AUTH_FAILED", f"SSH to physical host {hv.host} failed: {e}", cause=e,
        ) from e
    return ssh


class PhysicalPuller:
    """:class:`DiskPuller` for bare-metal Linux servers (P2V)."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        plan = _disk_plan(vm)
        if not plan:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"physical host {getattr(vm, 'name', '?')}: no block-device plan "
                "captured at discovery — re-run discovery on the source",
            )
        descriptors: list[DiskDescriptor] = []
        for index, disk in enumerate(plan):
            descriptors.append(
                DiskDescriptor(
                    disk_index=index,
                    source_format=SourceFormat.RAW,
                    size_bytes=int(disk.get("size_bytes") or 0),
                    locator=disk.get("device") or "",
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
        """Stream ``dd | gzip`` of the block device into a staged ``.raw`` file."""
        if not descriptor.locator:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND", "physical disk has no device locator",
            )
        ssh = _ssh_connect(hv)
        try:
            command = build_capture_command(descriptor.locator)
            logger.info("physical capture: %s -> %s", command, dest_path)
            _stdin, stdout, _stderr = ssh.exec_command(command, timeout=None)
            sha256 = _stream_gunzip_to_file(
                stdout, dest_path,
                expected_size=descriptor.size_bytes,
                progress_cb=progress_cb,
            )
            rc = stdout.channel.recv_exit_status()
            if rc != 0:
                raise ConversionError(
                    "ERR_OUTPUT_INVALID",
                    f"remote dd|gzip exited {rc} for {descriptor.locator}",
                )
        finally:
            ssh.close()
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
        """Stream the raw to worker scratch, then qemu-img convert -> qcow2.

        The physical source has no qemu-img (POSIX-minimal), so unlike the
        Proxmox/KVM connectors the conversion runs on the worker, mirroring the
        VMware Workstation pull-then-convert connector.
        """
        if target_format != "qcow2":
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"physical connector only produces qcow2, got {target_format!r}",
            )
        raw_tmp = dest_path.with_suffix(".raw")
        try:
            self.pull_disk(
                hv, vm, descriptor, raw_tmp, cold=cold, progress_cb=progress_cb,
            )
            _local_raw_to_qcow2(raw_tmp, dest_path)
            sha256 = _sha256_of(dest_path)
        finally:
            raw_tmp.unlink(missing_ok=True)
        return PullResult(
            staged_path=dest_path,
            source_format=SourceFormat.QCOW2,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )


# Structural conformance check (Protocol) — kept explicit for readers.
_: DiskPuller = PhysicalPuller()
