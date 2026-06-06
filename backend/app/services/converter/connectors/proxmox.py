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
import re
import shlex
from pathlib import Path
from typing import List, Optional

from app.core.ssh import apply_host_key_policy
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


# Disk-bearing config keys on Proxmox VMs: a bus name immediately followed by an
# index (``scsi0``, ``virtio1``, ``sata2``, ``ide0``). The trailing ``\d+`` is what
# makes this safe — a plain ``startswith`` prefix match also catches controller /
# feature keys that merely share a bus prefix but are NOT disks, e.g.
#   * ``scsihw: virtio-scsi-single``  (the SCSI controller model)
#   * ``virtiofs0: ...``              (a virtiofs directory share)
# which would otherwise be pulled as bogus disks and fail with ERR_DISK_NOT_FOUND.
_DISK_KEY_RE = re.compile(r"^(?:scsi|virtio|sata|ide)\d+$")
# ``ide2: ...media=cdrom`` etc. — never pull
_NON_DISK_HINT = "media=cdrom"


def _is_disk_key(key: str) -> bool:
    """True only for real disk bus keys (``scsi0``), not controllers (``scsihw``)."""
    return bool(_DISK_KEY_RE.match(key))

# Audit H-01 : un volid PVE est de la forme `storage:identifiant`. On le
# restreint à un jeu de caractères sûr afin qu'il ne puisse pas s'échapper
# de la commande shell distante `pvesm path <volid>`.
_VOLID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")


def _validate_volid(volid: str) -> None:
    """Rejette un identifiant de volume qui n'est pas un volid PVE simple."""
    if not volid or not _VOLID_RE.fullmatch(volid):
        raise ConversionError(
            "ERR_DISK_NOT_FOUND",
            f"identifiant de volume Proxmox invalide : {volid!r}",
        )


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


def _proxmox_api_user(hv: Hypervisor) -> str:
    """Complete the Proxmox REST API user with its realm (e.g. ``root`` -> ``root@pam``).

    Mirrors the discovery connector (``discovery.py``): the proxmoxer REST API
    authenticates as ``user@realm`` while SSH/SFTP logs in as the bare OS user
    (``root``). Only the REST client needs the realm suffix — adding it to the
    SSH login would break it.
    """
    cfg = hv.connection_config or {}
    realm = cfg.get("realm") or "pam"
    user = hv.username or "root"
    if "@" not in user:
        user = f"{user}@{realm}"
    return user


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

        password = hv.password_plain
        if not password:
            raise ConversionError(
                "ERR_HV_CREDENTIALS_MISSING",
                f"No usable credential for Proxmox host {hv.host} "
                f"(ciphertext absent or undecryptable; see vault.decrypt log lines)",
            )
        try:
            client = ProxmoxAPI(
                hv.host,
                user=_proxmox_api_user(hv),
                password=password,
                verify_ssl=bool(hv.verify_ssl),
                port=hv.port or 8006,
            )
        except Exception as e:  # NOSONAR — proxmoxer raises various types
            raise ConversionError(
                "ERR_HV_AUTH_FAILED",
                f"Proxmox auth failed: {e}",
                cause=e,
            ) from e

        node, vmid = self._resolve_vm(client, vm)
        try:
            config = client.nodes(node).qemu(vmid).config.get()
        except Exception as e:  # NOSONAR
            raise ConversionError(
                "ERR_VM_NOT_FOUND",
                f"Could not read config for vmid={vmid} on node={node}: {e}",
                cause=e,
            ) from e

        descriptors: list[DiskDescriptor] = []
        index = 0
        for key in sorted(config.keys()):
            if not _is_disk_key(key):
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
        """Convert+compress the disk ON the PVE node, then pull the small qcow2.

        Used by the convert-on-source SFTP transit mode: instead of pulling the
        full RAW volume and converting in-cluster, we run ``qemu-img convert -c``
        on the Proxmox node (the data is local there) and only transfer the
        compressed result. For a cold migration the VM is stopped before the
        read so the guest filesystem / PostgreSQL is quiescent, then restarted.
        """
        try:
            node, vmid_s, _key, volid = descriptor.locator.split("|", 3)
        except ValueError as e:
            raise ConversionError(
                "ERR_INTERNAL",
                f"malformed Proxmox locator: {descriptor.locator!r}",
                cause=e,
            ) from e
        vmid = int(vmid_s)
        _validate_volid(volid)
        remote_tmp = f"/tmp/shiftwise-{node}-{vmid}-d{int(descriptor.disk_index)}.{target_format}"

        ssh = self._connect_node(hv)
        stopped_here = False
        try:
            volpath = self._exec(ssh, f"pvesm path {shlex.quote(volid)}", timeout=30)
            if not volpath:
                raise ConversionError(
                    "ERR_DISK_NOT_FOUND", f"pvesm path returned nothing for {volid}",
                )
            if cold:
                stopped_here = self._stop_vm_if_running(ssh, vmid)
            # -c = sparse-aware compression; turns a mostly-empty 8 GB disk into
            # a few hundred MB. activeDeadline handled by the long exec timeout.
            self._exec(
                ssh,
                f"qemu-img convert -O {target_format} -c "
                f"{shlex.quote(volpath)} {shlex.quote(remote_tmp)}",
                timeout=6 * 3600,
                expect_rc0=True,
            )
            remote_size = int(self._exec(ssh, f"stat -c %s {shlex.quote(remote_tmp)}") or 0)
        finally:
            if stopped_here:
                # Best-effort restore of the source VM power state.
                try:
                    self._exec(ssh, f"qm start {vmid}", timeout=120)
                except Exception:  # NOSONAR — restart failure must not mask result
                    logger.warning("could not restart source VM %s after convert", vmid)
            ssh.close()

        # Pull the small qcow2 to the worker scratch (reuses the SFTP path).
        sha256 = self._sftp_pull(
            hv=hv, remote_path=remote_tmp, dest_path=dest_path,
            expected_size=remote_size, progress_cb=progress_cb,
        )
        # Remove the node-side temp.
        try:
            cleanup = self._connect_node(hv)
            self._exec(cleanup, f"rm -f {shlex.quote(remote_tmp)}", timeout=30)
            cleanup.close()
        except Exception:  # NOSONAR — leftover /tmp file is harmless
            logger.debug("could not remove node temp %s", remote_tmp, exc_info=True)

        out_fmt = SourceFormat.QCOW2 if target_format == "qcow2" else SourceFormat.RAW
        return PullResult(
            staged_path=dest_path,
            source_format=out_fmt,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    @staticmethod
    def _connect_node(hv: Hypervisor):
        """Open a paramiko SSH session to the PVE node (bare OS user)."""
        import paramiko  # type: ignore

        password = hv.password_plain
        if not password:
            raise ConversionError(
                "ERR_HV_CREDENTIALS_MISSING",
                f"No usable credential for Proxmox host {hv.host}",
            )
        ssh = paramiko.SSHClient()
        apply_host_key_policy(ssh)
        try:
            ssh.connect(
                hostname=hv.host, port=22, username=hv.username, password=password,
                timeout=30, allow_agent=False, look_for_keys=False,
            )
        except Exception as e:  # NOSONAR
            raise ConversionError(
                "ERR_HV_AUTH_FAILED",
                f"SSH to Proxmox node {hv.host} failed: {e}",
                cause=e,
            ) from e
        return ssh

    @staticmethod
    def _exec(ssh, cmd: str, *, timeout: int = 60, expect_rc0: bool = False) -> str:
        _in, out, err = ssh.exec_command(cmd, timeout=timeout)
        stdout = out.read().decode("utf-8", "replace").strip()
        stderr = err.read().decode("utf-8", "replace").strip()
        rc = out.channel.recv_exit_status()
        if expect_rc0 and rc != 0:
            raise ConversionError(
                "ERR_TOOL_FAILED",
                f"command failed (rc={rc}): {cmd!r} :: {stderr or stdout or 'no output'}",
            )
        return stdout

    @classmethod
    def _stop_vm_if_running(cls, ssh, vmid: int) -> bool:
        """Stop the VM if running; wait until stopped. Returns True if we stopped it."""
        import time
        status = cls._exec(ssh, f"qm status {vmid}", timeout=30)
        if "running" not in status:
            return False
        cls._exec(ssh, f"qm stop {vmid}", timeout=120)
        for _ in range(30):
            if "stopped" in cls._exec(ssh, f"qm status {vmid}", timeout=30):
                return True
            time.sleep(2)
        raise ConversionError(
            "ERR_HV_UNREACHABLE", f"VM {vmid} did not stop within timeout",
        )

    # --- internal helpers ---

    @staticmethod
    def _resolve_vm(client, vm: VirtualMachine) -> tuple[str, int]:
        """Return (node, vmid) from the cluster resources index."""
        try:
            resources = client.cluster.resources.get(type="vm")
        except Exception as e:  # NOSONAR
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
        _validate_volid(volid)  # Audit H-01 — refuse toute injection shell
        try:
            import paramiko  # type: ignore
        except ImportError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                "paramiko not installed in worker image",
                cause=e,
            ) from e

        password = hv.password_plain
        if not password:
            raise ConversionError(
                "ERR_HV_CREDENTIALS_MISSING",
                f"No usable credential for Proxmox host {hv.host} "
                f"(ciphertext absent or undecryptable; see vault.decrypt log lines)",
            )
        ssh = paramiko.SSHClient()
        apply_host_key_policy(ssh)  # Audit H-02 — vérifie les clés d'hôte SSH
        try:
            ssh.connect(
                hostname=hv.host,
                port=22,
                username=hv.username,
                password=password,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as e:  # NOSONAR
            raise ConversionError(
                "ERR_HV_AUTH_FAILED",
                f"SSH to Proxmox node {hv.host} failed: {e}",
                cause=e,
            ) from e

        try:
            _stdin, stdout, stderr = ssh.exec_command(
                f"pvesm path {shlex.quote(volid)}",
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

        password = hv.password_plain
        if not password:
            raise ConversionError(
                "ERR_HV_CREDENTIALS_MISSING",
                f"No usable credential for Proxmox host {hv.host} "
                f"(ciphertext absent or undecryptable; see vault.decrypt log lines)",
            )
        ssh = paramiko.SSHClient()
        apply_host_key_policy(ssh)  # Audit H-02 — vérifie les clés d'hôte SSH
        try:
            ssh.connect(
                hostname=hv.host,
                port=22,
                username=hv.username,
                password=password,
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
                            except Exception:  # NOSONAR
                                logger.debug("progress_cb raised", exc_info=True)
            finally:
                sftp.close()
        except Exception as e:  # NOSONAR
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
