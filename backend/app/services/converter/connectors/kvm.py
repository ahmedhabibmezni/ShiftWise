"""
KVM/libvirt connector — pull a VM disk by reading the libvirt domain XML
and SCP'ing the backing file from the host.

Strategy (cold pull):
1. paramiko SSH to the libvirt host.
2. ``virsh dumpxml <vm>`` and parse ``<disk type='file' device='disk'>`` entries.
3. SFTP each disk's ``<source file=...>`` into NFS, computing sha256 inline.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

from app.core.ssh import apply_host_key_policy
from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.connectors.base import detect_format_from_extension
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)

logger = logging.getLogger(__name__)


def _ssh_connect(hv: Hypervisor):
    try:
        import paramiko  # type: ignore
    except ImportError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND",
            "paramiko not installed in worker image",
            cause=e,
        ) from e
    ssh = paramiko.SSHClient()
    apply_host_key_policy(ssh)  # Audit H-02 — vérifie les clés d'hôte SSH
    try:
        ssh.connect(
            hostname=hv.host,
            port=hv.port or 22,
            username=hv.username,
            password=hv.password_plain,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:  # NOSONAR
        raise ConversionError(
            "ERR_HV_AUTH_FAILED",
            f"SSH to KVM host {hv.host} failed: {e}",
            cause=e,
        ) from e
    return ssh


def _virsh_xml(ssh, vm_name: str) -> str:
    # Match libvirt name first, then UUID — `virsh dumpxml` accepts either.
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "", vm_name)
    if not safe:
        raise ConversionError("ERR_VM_NOT_FOUND", f"unsafe VM name {vm_name!r}")
    _stdin, stdout, stderr = ssh.exec_command(
        f"virsh dumpxml -- {safe}", timeout=15,
    )
    xml = stdout.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if rc != 0 or not xml.strip():
        err = stderr.read().decode("utf-8", errors="replace")
        raise ConversionError(
            "ERR_VM_NOT_FOUND",
            f"virsh dumpxml {safe} failed (rc={rc}): {err}",
        )
    return xml


def _parse_disks(xml_text: str) -> list[tuple[str, Optional[str]]]:
    """Return list of (source_file, driver_format) for type='file' disks."""
    out: list[tuple[str, Optional[str]]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ConversionError(
            "ERR_INTERNAL", f"could not parse libvirt XML: {e}", cause=e,
        ) from e
    for disk in root.findall(".//devices/disk"):
        if disk.get("device") != "disk" or disk.get("type") != "file":
            continue
        src = disk.find("source")
        drv = disk.find("driver")
        if src is None:
            continue
        path = src.get("file")
        if not path:
            continue
        fmt = drv.get("type") if drv is not None else None
        out.append((path, fmt))
    return out


class KvmPuller:
    """:class:`DiskPuller` for KVM/libvirt."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        ssh = _ssh_connect(hv)
        try:
            xml = _virsh_xml(ssh, vm.name)
            disks = _parse_disks(xml)
            descriptors: list[DiskDescriptor] = []
            for index, (path, fmt) in enumerate(disks):
                # Try driver hint first, fall back to extension.
                fmt_hint = fmt or detect_format_from_extension(path) or "raw"
                try:
                    source_format = SourceFormat(fmt_hint)
                except ValueError:
                    source_format = SourceFormat.RAW
                # Size lookup via remote `stat -c %s`
                size = self._remote_size(ssh, path)
                descriptors.append(
                    DiskDescriptor(
                        disk_index=index,
                        source_format=source_format,
                        size_bytes=size,
                        locator=path,
                    )
                )
            return descriptors
        finally:
            ssh.close()

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
                "Live blockcopy not implemented yet — power VM off",
            )

        import hashlib
        ssh = _ssh_connect(hv)
        try:
            sftp = ssh.open_sftp()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            partial = dest_path.with_suffix(dest_path.suffix + ".partial")
            h = hashlib.sha256()
            try:
                with sftp.open(descriptor.locator, "rb") as fin, open(partial, "wb") as fout:
                    fin.prefetch()
                    bytes_done = 0
                    chunk = 1024 * 1024
                    while True:
                        buf = fin.read(chunk)
                        if not buf:
                            break
                        fout.write(buf)
                        h.update(buf)
                        bytes_done += len(buf)
                        if progress_cb is not None:
                            try:
                                progress_cb(bytes_done, descriptor.size_bytes or bytes_done)
                            except Exception:  # NOSONAR
                                logger.debug("progress_cb raised", exc_info=True)
                partial.replace(dest_path)
            except Exception as e:  # NOSONAR
                if partial.exists():
                    partial.unlink(missing_ok=True)
                raise ConversionError(
                    "ERR_NETWORK_TIMEOUT",
                    f"SFTP pull from {hv.host}:{descriptor.locator} failed: {e}",
                    cause=e,
                ) from e
            finally:
                sftp.close()
        finally:
            ssh.close()

        size = dest_path.stat().st_size
        return PullResult(
            staged_path=dest_path,
            source_format=descriptor.source_format,
            size_bytes=size,
            sha256=h.hexdigest(),
        )

    @staticmethod
    def _remote_size(ssh, path: str) -> int:
        # Quote single-quotes safely
        quoted = path.replace("'", "'\\''")
        _stdin, stdout, _stderr = ssh.exec_command(
            f"stat -c %s -- '{quoted}'", timeout=10,
        )
        out = stdout.read().decode("utf-8", errors="replace").strip()
        try:
            return int(out)
        except ValueError:
            return 0
