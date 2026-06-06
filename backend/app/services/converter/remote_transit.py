"""
Remote transit uploader — pushes a converted qcow2 onto the cluster's NFS
export over SFTP, optionally through a bastion jump host.

Why this exists
---------------
In the dev/demo topology the orchestrating worker runs on a laptop that can
reach the Proxmox source but NOT the cluster's NFS (firewalled; the only path
to the internal NFS host is via the bastion). The in-cluster Jobs (adapter,
migrator) read the qcow2 from the NFS-backed transit PVC. So the worker has to
deposit the converted qcow2 on the NFS export, and the only reachable route is
``laptop -> bastion -> nfs-host`` over SSH.

Logical vs physical paths
-------------------------
The in-cluster Jobs see the transit volume mounted at
``settings.CONVERTER_TRANSIT_ROOT`` (e.g. ``/mnt/shiftwise-transit``). On the
NFS host the same bytes live under ``CONVERTER_SFTP_TARGET_EXPORT`` (the PV's
``spec.nfs.path``). This module maps a POSIX-relative path (``{tenant}/outputs/
{group}/{disk}.qcow2``) onto ``{export}/{rel}`` on the host. Callers keep using
the logical ``/mnt/shiftwise-transit/{rel}`` path for the Job manifests.

Only used when ``settings.CONVERTER_SOURCE_CONVERT_SFTP`` is True. The
production path (in-cluster worker sharing the PVC mount) never imports this.
"""

from __future__ import annotations

import logging
import posixpath
import socket
import time
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.ssh import apply_host_key_policy
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import ProgressCallback

logger = logging.getLogger(__name__)

_CONNECT_RETRIES = 6
_CONNECT_BACKOFF_SECONDS = 2


def _ssh_client():
    """paramiko client with the project's audited host-key policy (H-02).

    ``apply_host_key_policy`` loads the system known_hosts and REJECTS unknown
    hosts by default; AutoAdd (trust-on-first-use) is only used when the dev
    flag ``SSH_AUTO_ADD_HOST_KEYS`` is set. Operators enabling this bridge must
    pre-populate known_hosts for the bastion + NFS target, or opt into the dev
    flag knowingly (same convention as the Proxmox/KVM connectors).
    """
    import paramiko  # type: ignore

    client = paramiko.SSHClient()
    apply_host_key_policy(client)
    return client


class RemoteTransit:
    """SSH/SFTP handle onto the NFS host, optionally via a bastion jump.

    Use as a context manager so the (up to two) SSH connections are always
    torn down::

        with RemoteTransit.from_settings() as rt:
            rt.ensure_dir("nextstep/outputs/<uuid>")
            rt.put_file(local_qcow2, "nextstep/outputs/<uuid>/0.qcow2")
    """

    def __init__(
        self,
        *,
        target_host: str,
        target_port: int,
        target_user: str,
        target_password: str,
        export_root: str,
        jump_host: str = "",
        jump_port: int = 22,
        jump_user: str = "root",
        jump_password: str = "",
    ) -> None:
        if not target_host or not export_root:
            raise ConversionError(
                "ERR_INTERNAL",
                "RemoteTransit misconfigured: target host/export are required",
            )
        self._target = (target_host, target_port, target_user, target_password)
        self._export_root = export_root.rstrip("/")
        self._jump = (
            (jump_host, jump_port, jump_user, jump_password) if jump_host else None
        )
        self._bastion = None
        self._client = None
        self._sftp = None

    @classmethod
    def from_settings(cls) -> "RemoteTransit":
        return cls(
            target_host=settings.CONVERTER_SFTP_TARGET_HOST,
            target_port=settings.CONVERTER_SFTP_TARGET_PORT,
            target_user=settings.CONVERTER_SFTP_TARGET_USER,
            target_password=settings.CONVERTER_SFTP_TARGET_PASSWORD,
            export_root=settings.CONVERTER_SFTP_TARGET_EXPORT,
            jump_host=settings.CONVERTER_SFTP_JUMP_HOST,
            jump_port=settings.CONVERTER_SFTP_JUMP_PORT,
            jump_user=settings.CONVERTER_SFTP_JUMP_USER,
            jump_password=settings.CONVERTER_SFTP_JUMP_PASSWORD,
        )

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "RemoteTransit":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        last_err: Optional[Exception] = None
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                self._connect_once()
                return
            except Exception as e:  # NOSONAR — flaky VPN: retry any failure
                last_err = e
                self.close()
                logger.warning(
                    "RemoteTransit connect attempt %d/%d failed: %s",
                    attempt, _CONNECT_RETRIES, e,
                )
                time.sleep(_CONNECT_BACKOFF_SECONDS)
        raise ConversionError(
            "ERR_NETWORK_TIMEOUT",
            f"RemoteTransit could not reach NFS host {self._target[0]} "
            f"(via jump {self._jump[0] if self._jump else 'none'}): {last_err}",
            cause=last_err,
        )

    def _connect_once(self) -> None:
        host, port, user, pw = self._target
        sock = None
        if self._jump is not None:
            jhost, jport, juser, jpw = self._jump
            jsock = socket.create_connection((jhost, jport), timeout=10)
            self._bastion = _ssh_client()
            self._bastion.connect(
                jhost, port=jport, username=juser, password=jpw, sock=jsock,
                timeout=20, banner_timeout=30, auth_timeout=30,
                allow_agent=False, look_for_keys=False,
            )
            sock = self._bastion.get_transport().open_channel(
                "direct-tcpip", (host, port), ("127.0.0.1", 0), timeout=15,
            )
        else:
            sock = socket.create_connection((host, port), timeout=10)
        self._client = _ssh_client()
        self._client.connect(
            host, port=port, username=user, password=pw, sock=sock,
            timeout=20, banner_timeout=30, auth_timeout=30,
            allow_agent=False, look_for_keys=False,
        )
        self._sftp = self._client.open_sftp()

    def close(self) -> None:
        for attr in ("_sftp", "_client", "_bastion"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # NOSONAR — best-effort teardown
                    pass
                setattr(self, attr, None)

    # --- operations --------------------------------------------------------

    def _abs(self, rel: str) -> str:
        rel = rel.lstrip("/")
        if ".." in rel.split("/"):
            raise ConversionError("ERR_INTERNAL", f"unsafe transit rel path: {rel!r}")
        return posixpath.join(self._export_root, rel)

    def _run(self, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        _in, out, err = self._client.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        return rc, o.strip(), e.strip()

    def ensure_dir(self, rel_dir: str) -> None:
        target = self._abs(rel_dir)
        rc, _o, e = self._run(f"mkdir -p {_shq(target)}")
        if rc != 0:
            raise ConversionError(
                "ERR_NFS_INSUFFICIENT_SPACE",
                f"could not create transit dir {target}: {e or 'mkdir failed'}",
            )

    def exists(self, rel: str) -> bool:
        rc, _o, _e = self._run(f"test -e {_shq(self._abs(rel))}")
        return rc == 0

    def size(self, rel: str) -> int:
        rc, out, _e = self._run(f"stat -c %s {_shq(self._abs(rel))}")
        if rc != 0 or not out.isdigit():
            return 0
        return int(out)

    def remove(self, rel: str) -> None:
        self._run(f"rm -f {_shq(self._abs(rel))}")

    def free_bytes(self, rel_dir: str = "") -> int:
        target = self._abs(rel_dir) if rel_dir else self._export_root
        rc, out, _e = self._run(f"df -P -B1 {_shq(target)} | tail -1 | awk '{{print $4}}'")
        if rc != 0 or not out.isdigit():
            return 0
        return int(out)

    def put_file(
        self,
        local_src: Path,
        rel_dst: str,
        *,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> int:
        """Upload ``local_src`` to ``{export}/{rel_dst}``. Returns bytes sent.

        Atomic publish: write to ``<dst>.partial`` then rename. The SFTP write
        is pipelined for throughput over the high-latency link.
        """
        total = local_src.stat().st_size
        dst = self._abs(rel_dst)
        partial = dst + ".partial"
        self.ensure_dir(posixpath.dirname(rel_dst))
        sent = 0
        chunk = 1024 * 1024
        with self._sftp.open(partial, "wb") as fout, open(local_src, "rb") as fin:
            fout.set_pipelined(True)
            while True:
                buf = fin.read(chunk)
                if not buf:
                    break
                fout.write(buf)
                sent += len(buf)
                if progress_cb is not None:
                    try:
                        progress_cb(sent, total or sent)
                    except Exception:  # NOSONAR — progress must never abort upload
                        logger.debug("progress_cb raised", exc_info=True)
        rc, _o, e = self._run(f"mv -f {_shq(partial)} {_shq(dst)}")
        if rc != 0:
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"could not publish uploaded transit file {dst}: {e or 'mv failed'}",
            )
        # World-writable: the in-cluster Adapter (virt-customize) opens the
        # qcow2 READ-WRITE under an arbitrary OpenShift-assigned UID. We upload
        # as root, so the file would otherwise be root:root 0644 and the
        # adapter's own chmod would fail ("not owner") → qemu cannot open the
        # drive RW → guestfs_launch fails. Setting 0666 here (as root) makes it
        # writable by any UID. The data sits on an internal NFS share reachable
        # only by authorised SAs, so the broad mode is acceptable.
        self._run(f"chmod 0666 {_shq(dst)}")
        return sent


def _shq(s: str) -> str:
    """Minimal shell single-quote escaping for remote paths."""
    return "'" + s.replace("'", "'\"'\"'") + "'"
