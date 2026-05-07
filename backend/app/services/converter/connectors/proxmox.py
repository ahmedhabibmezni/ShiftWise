"""
Proxmox VE connector — pull a VM disk via the proxmoxer REST client + SCP.

Strategy (cold pull, default):
1. Authenticate via proxmoxer (token or password).
2. Resolve the VM by ``source_uuid`` -> (node, vmid) using the cluster resources.
3. Read ``config`` to enumerate disks (scsi0..N, virtio0..N, ide0..N, sata0..N).
4. For each disk, parse the storage volume id (e.g. ``local-lvm:vm-101-disk-0``).
5. Translate volume id -> filesystem path on the PVE node via the ``content``
   API (or, when LVM-backed, via ``pvesm path`` over SSH).
6. Stream the file from the PVE node to NFS using paramiko SFTP, computing
   sha256 inline.

Live pull is not supported in this iteration — Proxmox guests need an explicit
snapshot for safe live copy and we punt on that until tested.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.connectors.base import (
    detect_format_from_extension,
)
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)

logger = logging.getLogger(__name__)


# Disk-bearing config keys on Proxmox VMs
_DISK_KEYS = ("scsi", "virtio", "sata", "ide")
# ``ide2: ...media=cdrom`` etc. — never pull
_NON_DISK_HINT = "media=cdrom"


def _parse_disk_entry(entry: str) -> Optional[tuple[str, dict[str, str]]]:
    """Parse ``local-lvm:vm-101-disk-0,size=32G`` -> (volid, opts)."""
    if not entry or _NON_DISK_HINT in entry:
        return None
    parts = entry.split(",")
    volid = parts[0].strip()
    opts: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            opts[k.strip()] = v.strip()
    return volid, opts


def _size_bytes_from_opts(opts: dict[str, str]) -> int:
    raw = opts.get("size")
    if not raw:
        return 0
    raw = raw.strip().upper()
    multipliers = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    if raw[-1] in multipliers:
        return int(float(raw[:-1]) * multipliers[raw[-1]])
    try:
        return int(raw)
    except ValueError:
        return 0


class ProxmoxPuller:
    """:class:`DiskPuller` for Proxmox VE."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        try:
            from proxmoxer import ProxmoxAPI  # type: ignore
        except ImportError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                "proxmoxer not installed in worker image",
                cause=e,
            ) from e

        try:
            client = ProxmoxAPI(
                hv.host,
                user=hv.username,
                password=hv.password,
                verify_ssl=bool(hv.verify_ssl),
                port=hv.port or 8006,
            )
        except Exception as e:  # noqa: BLE001 — proxmoxer raises various types
            raise ConversionError(
                "ERR_HV_AUTH_FAILED",
                f"Proxmox auth failed: {e}",
                cause=e,
            ) from e

        node, vmid = self._resolve_vm(client, vm)
        try:
            config = client.nodes(node).qemu(vmid).config.get()
        except Exception as e:  # noqa: BLE001
            raise ConversionError(
                "ERR_VM_NOT_FOUND",
                f"Could not read config for vmid={vmid} on node={node}: {e}",
                cause=e,
            ) from e

        descriptors: list[DiskDescriptor] = []
        index = 0
        for key in sorted(config.keys()):
            if not any(key.startswith(p) for p in _DISK_KEYS):
                continue
            parsed = _parse_disk_entry(str(config[key]))
            if parsed is None:
                continue
            volid, opts = parsed
            size = _size_bytes_from_opts(opts)
            fmt_hint = detect_format_from_extension(volid) or "raw"
            try:
                source_format = SourceFormat(fmt_hint)
            except ValueError:
                # LVM/ZFS volumes report no extension — treat as raw block.
                source_format = SourceFormat.RAW
            descriptors.append(
                DiskDescriptor(
                    disk_index=index,
                    source_format=source_format,
                    size_bytes=size,
                    locator=f"{node}|{vmid}|{key}|{volid}",
                )
            )
            index += 1
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
        if not cold:
            raise ConversionError(
                "ERR_VM_RUNNING_NEEDS_COLD",
                "Live pull not implemented for Proxmox; power VM off first",
            )

        try:
            node, vmid_s, _key, volid = descriptor.locator.split("|", 3)
        except ValueError as e:
            raise ConversionError(
                "ERR_INTERNAL",
                f"malformed Proxmox locator: {descriptor.locator!r}",
                cause=e,
            ) from e

        # Resolve the on-disk path of the volume. PVE exposes it via the
        # ``content`` API for file-backed storages, and via SSH+pvesm for
        # block storages. Both paths are SFTP-fetchable from the PVE node.
        remote_path = self._resolve_volume_path(hv, node, volid)
        sha256 = self._sftp_pull(
            hv=hv,
            remote_path=remote_path,
            dest_path=dest_path,
            expected_size=descriptor.size_bytes,
            progress_cb=progress_cb,
        )
        actual_size = dest_path.stat().st_size
        return PullResult(
            staged_path=dest_path,
            source_format=descriptor.source_format,
            size_bytes=actual_size,
            sha256=sha256,
        )

    # --- internal helpers ---

    @staticmethod
    def _resolve_vm(client, vm: VirtualMachine) -> tuple[str, int]:
        """Return (node, vmid) from the cluster resources index."""
        try:
            resources = client.cluster.resources.get(type="vm")
        except Exception as e:  # noqa: BLE001
            raise ConversionError(
                "ERR_HV_UNREACHABLE",
                f"Could not list cluster resources: {e}",
                cause=e,
            ) from e

        # Match by source_uuid (preferred) or by name as fallback.
        for r in resources:
            r_uuid = (r.get("uuid") or "").lower()
            if vm.source_uuid and r_uuid and r_uuid == vm.source_uuid.lower():
                return r["node"], int(r["vmid"])
        for r in resources:
            if r.get("name") == vm.name:
                return r["node"], int(r["vmid"])

        raise ConversionError(
            "ERR_VM_NOT_FOUND",
            f"VM {vm.name!r} (uuid={vm.source_uuid}) not found in Proxmox cluster",
        )

    @staticmethod
    def _resolve_volume_path(hv: Hypervisor, node: str, volid: str) -> str:
        """Run ``pvesm path <volid>`` on ``node`` over SSH to get the FS path."""
        try:
            import paramiko  # type: ignore
        except ImportError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                "paramiko not installed in worker image",
                cause=e,
            ) from e

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=hv.host,
                port=22,
                username=hv.username,
                password=hv.password,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as e:  # noqa: BLE001
            raise ConversionError(
                "ERR_HV_AUTH_FAILED",
                f"SSH to Proxmox node {hv.host} failed: {e}",
                cause=e,
            ) from e

        try:
            _stdin, stdout, stderr = ssh.exec_command(
                f"pvesm path {volid}",
                timeout=15,
            )
            path = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            rc = stdout.channel.recv_exit_status()
        finally:
            ssh.close()

        if rc != 0 or not path:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"pvesm path {volid} failed (rc={rc}): {err or 'no output'}",
            )
        return path

    @staticmethod
    def _sftp_pull(
        *,
        hv: Hypervisor,
        remote_path: str,
        dest_path: Path,
        expected_size: int,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        try:
            import paramiko  # type: ignore
        except ImportError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                "paramiko not installed",
                cause=e,
            ) from e

        import hashlib

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        h = hashlib.sha256()

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=hv.host,
                port=22,
                username=hv.username,
                password=hv.password,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            sftp = ssh.open_sftp()
            try:
                with sftp.open(remote_path, "rb") as fin, open(partial, "wb") as fout:
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
                                progress_cb(bytes_done, expected_size or bytes_done)
                            except Exception:  # noqa: BLE001
                                logger.debug("progress_cb raised", exc_info=True)
            finally:
                sftp.close()
        except Exception as e:  # noqa: BLE001
            if partial.exists():
                partial.unlink(missing_ok=True)
            raise ConversionError(
                "ERR_NETWORK_TIMEOUT",
                f"SFTP pull from {hv.host}:{remote_path} failed: {e}",
                cause=e,
            ) from e
        finally:
            ssh.close()

        partial.replace(dest_path)
        return h.hexdigest()
