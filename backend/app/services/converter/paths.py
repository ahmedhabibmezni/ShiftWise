"""
NFS transit zone path layout — single source of truth.

Layout::

    {root}/{tenant_id}/
        sources/{vm_id}/{disk_index}.{ext}
        work/{group_uuid}/{disk_index}.tmp
        outputs/{group_uuid}/{disk_index}.{ext}
        logs/{group_uuid}/{disk_index}.log

The converter writes only inside ``work/`` and ``outputs/``. Atomic publish
is ``work/...tmp`` → ``rename`` → ``outputs/...``. No partial files in
``outputs/`` by construction.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def _safe_segment(value: str) -> str:
    """Reject path traversal and absolute paths in user-controlled segments."""
    if not value:
        raise ValueError("empty path segment")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"unsafe path segment: {value!r}")
    return value


def transit_root() -> Path:
    return Path(settings.CONVERTER_TRANSIT_ROOT)


def tenant_root(tenant_id: str) -> Path:
    return transit_root() / _safe_segment(tenant_id)


def sources_dir(tenant_id: str, vm_id: int) -> Path:
    return tenant_root(tenant_id) / "sources" / str(int(vm_id))


def work_dir(tenant_id: str, group_uuid: str) -> Path:
    return tenant_root(tenant_id) / "work" / _safe_segment(group_uuid)


def outputs_dir(tenant_id: str, group_uuid: str) -> Path:
    return tenant_root(tenant_id) / "outputs" / _safe_segment(group_uuid)


def logs_dir(tenant_id: str, group_uuid: str) -> Path:
    return tenant_root(tenant_id) / "logs" / _safe_segment(group_uuid)


def staged_path(tenant_id: str, group_uuid: str, disk_index: int) -> Path:
    return work_dir(tenant_id, group_uuid) / f"{int(disk_index)}.tmp"


def output_path(
    tenant_id: str,
    group_uuid: str,
    disk_index: int,
    extension: str,
) -> Path:
    ext = extension.lstrip(".").lower()
    if not ext.isalnum():
        raise ValueError(f"unsafe extension: {extension!r}")
    return outputs_dir(tenant_id, group_uuid) / f"{int(disk_index)}.{ext}"


def log_path(tenant_id: str, group_uuid: str, disk_index: int) -> Path:
    return logs_dir(tenant_id, group_uuid) / f"{int(disk_index)}.log"


def ensure_dirs(*paths: Path) -> None:
    """Create parent dirs (mkdir -p) — caller still owns concurrency."""
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
