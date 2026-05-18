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
from pathlib import Path
from typing import Optional

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
