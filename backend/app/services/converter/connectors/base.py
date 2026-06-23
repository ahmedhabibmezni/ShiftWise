"""
Shared helpers for connector implementations.

Keep this module deliberately small — it's not an inheritance base, only a
home for utilities that would otherwise be duplicated. Connectors implement
:class:`DiskPuller` directly (Protocol, structural typing).
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import ProgressCallback

logger = logging.getLogger(__name__)


_HASH_CHUNK = 1024 * 1024  # 1 MiB


def detect_format_from_extension(path: str) -> Optional[str]:
    """Best-effort SourceFormat hint from filename — caller validates with qemu-img."""
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"vmdk", "vhd", "vhdx", "qcow2", "raw", "img"}:
        return "raw" if suffix == "img" else suffix
    return None


def stream_copy(
    src: Path,
    dest: Path,
    *,
    expected_size: int,
    progress_cb: Optional[ProgressCallback] = None,
    chunk_size: int = _HASH_CHUNK,
) -> str:
    """Copy ``src`` -> ``dest`` while computing SHA-256 and reporting progress.

    Atomic: writes to ``dest.with_suffix(dest.suffix + '.partial')`` then
    renames. On error, partial file is removed.

    Returns hex SHA-256 of the bytes copied. Raises ``ConversionError``.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    h = hashlib.sha256()
    bytes_done = 0
    try:
        with open(src, "rb") as fin, open(partial, "wb") as fout:
            while True:
                buf = fin.read(chunk_size)
                if not buf:
                    break
                fout.write(buf)
                h.update(buf)
                bytes_done += len(buf)
                if progress_cb is not None:
                    try:
                        progress_cb(bytes_done, expected_size)
                    except Exception:  # NOSONAR — never let a callback kill the copy
                        logger.debug("progress_cb raised", exc_info=True)
            fout.flush()
        partial.replace(dest)
        return h.hexdigest()
    except OSError as e:
        if partial.exists():
            partial.unlink(missing_ok=True)
        raise ConversionError(
            "ERR_NFS_TIMEOUT" if "timed out" in str(e).lower() else "ERR_INTERNAL",
            f"copy failed: {e}",
            cause=e,
        ) from e


def sha256_file(path: Path, progress_cb: Optional[ProgressCallback] = None) -> str:
    """Return hex SHA-256 of ``path``, streaming in 1 MiB chunks with progress.

    Shared by connectors that convert on/near the source and then need to
    fingerprint the local result before uploading it to the transit NFS.
    """
    h = hashlib.sha256()
    total = 0
    try:
        total = path.stat().st_size
    except OSError:
        total = 0
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
                except Exception:  # NOSONAR — a callback must never abort hashing
                    logger.debug("progress_cb raised", exc_info=True)
    return h.hexdigest()


def local_qemu_img_convert(
    src: Path,
    dest: Path,
    target_format: str,
    *,
    timeout: int = 6 * 3600,
) -> None:
    """Convert+compress ``src`` into ``dest`` with the worker-local ``qemu-img``.

    Used by every connector whose ``convert_on_source`` lands the disk on the
    worker first (oVirt ImageTransfer download, Hyper-V SMB pull, vSphere
    datastore download). ``-c`` sparse-compresses the output so only the small
    qcow2 crosses the slow uplink afterwards. The caller owns ``dest`` placement
    (``.partial`` / atomic rename). Raises ``ConversionError`` mapped to the
    standard buckets — symmetric with
    :meth:`VmwareWorkstationPuller._run_qemu_img_convert`.
    """
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
            timeout=timeout,
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


def replay_vhdx_log(src: Path, *, timeout: int = 1800) -> bool:
    """Single-shot ``qemu-img check -r all`` — replay a dirty VHDX log and report
    whether the image is now openable.

    A Hyper-V VM powered off with ``Stop-VM -Force`` (a hard turn-off — required
    when the guest has no integration services for a graceful ACPI shutdown)
    leaves its VHDX with an unreplayed journal log; ``qemu-img`` opens a
    conversion *source* read-only and refuses such an image
    (``contains a log that needs to be replayed``). ``check -r all`` opens it
    read-write and replays the log — idempotent, exactly what the guest's next
    boot would do, so it does not alter guest data.

    Returns ``True`` iff qemu-img opened the image and the check returned 0 (log
    replayed or already clean). Returns ``False`` on a transient open failure —
    the file handle is still held (``Stop-VM`` releases the VHDX handle
    asynchronously) or the file is momentarily absent (an automatic-checkpoint
    ``.avhdx`` mid-merge into its base) — or on real corruption. Best-effort: a
    missing ``qemu-img`` or a timeout also yields ``False``. A caller that just
    stopped a VM should poll this until ``True``
    (see :meth:`HyperVPuller._await_local_source_after_stop`).
    """
    qemu_img = settings.CONVERTER_LOCAL_QEMU_IMG
    cmd = [qemu_img, "check", "-r", "all", str(src)]
    try:
        result = subprocess.run(  # NOSONAR — local trusted tool, fixed argv
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:  # NOSONAR
        logger.warning("VHDX check/replay skipped for %s: %s", src, e)
        return False
    if result.returncode == 0:
        return True
    logger.debug(
        "qemu-img check -r all on %s rc=%s: %s",
        src, result.returncode,
        (result.stderr or result.stdout or "").strip()[:300],
    )
    return False


def free_space_bytes(path: Path) -> int:
    """Return free bytes on the filesystem hosting ``path`` (creating parents if needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return shutil.disk_usage(path.parent).free
    except OSError as e:
        raise ConversionError(
            "ERR_NFS_TIMEOUT",
            f"could not stat {path.parent}: {e}",
            cause=e,
        ) from e
