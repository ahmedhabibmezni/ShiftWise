"""
Transit NFS auto-discovery.

Reads the PV backing `transit-pvc` in the converter namespace at runtime
so that MIGRATOR_NFS_SERVER / MIGRATOR_NFS_PATH env vars don't have to be
set manually per deployment.

Cache: result is stored in a module-level tuple so each worker process only
hits the API once.  The cached value is valid for the lifetime of the worker
pod — the PV / NFS server never changes without a redeployment.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Tuple

from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.services.migrator.errors import MigratorError

if TYPE_CHECKING:
    from app.core.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

# Module-level cache — (server, path) or None when not yet discovered.
_CACHE: Optional[Tuple[str, str]] = None


def discover_transit_nfs(kv_client: "KubeVirtClient") -> Tuple[str, str]:
    """Return (nfs_server, nfs_path) for the transit PVC.

    Resolution order:
      1. Explicit env vars (MIGRATOR_NFS_SERVER + MIGRATOR_NFS_PATH both set)
      2. In-process cache (from a previous call this worker lifetime)
      3. Live lookup: PVC → PV → spec.nfs

    Raises MigratorError if discovery fails and no explicit config is set.
    """
    # Fast-path: operator explicitly configured both values.
    if settings.MIGRATOR_NFS_SERVER and settings.MIGRATOR_NFS_PATH:
        return settings.MIGRATOR_NFS_SERVER, settings.MIGRATOR_NFS_PATH

    global _CACHE
    if _CACHE is not None:
        return _CACHE

    _CACHE = _lookup_from_cluster(kv_client)
    return _CACHE


def _lookup_from_cluster(kv_client: "KubeVirtClient") -> Tuple[str, str]:
    pvc_namespace = settings.CONVERTER_K8S_NAMESPACE
    pvc_name = settings.CONVERTER_TRANSIT_PVC

    # Step 1: read the PVC to get the bound PV name.
    try:
        pvc = kv_client.get_pvc(name=pvc_name, namespace=pvc_namespace)
    except ApiException as e:
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"Cannot read transit PVC {pvc_namespace}/{pvc_name} "
            f"(status {e.status}). Set MIGRATOR_NFS_SERVER + "
            f"MIGRATOR_NFS_PATH or grant the worker SA pvc/get on "
            f"{pvc_namespace!r}.",
            cause=e,
        ) from e

    pv_name: Optional[str] = None
    if pvc.spec and pvc.spec.volume_name:
        pv_name = pvc.spec.volume_name

    if not pv_name:
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"Transit PVC {pvc_namespace}/{pvc_name} is not bound "
            f"(no spec.volumeName). Ensure the PVC is Bound before "
            f"launching migrations.",
        )

    # Step 2: read the PV to get spec.nfs.
    try:
        pv = kv_client.get_pv(name=pv_name)
    except ApiException as e:
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"Cannot read PersistentVolume {pv_name!r} "
            f"(status {e.status}). Grant the worker SA pv/get.",
            cause=e,
        ) from e

    nfs = None
    if pv.spec:
        nfs = pv.spec.nfs

    if nfs is None or not nfs.server or not nfs.path:
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"PV {pv_name!r} has no spec.nfs section (server={getattr(nfs, 'server', None)!r}, "
            f"path={getattr(nfs, 'path', None)!r}). Only NFS-backed transit "
            f"PVCs are supported. Set MIGRATOR_NFS_SERVER + MIGRATOR_NFS_PATH "
            f"to override.",
        )

    server: str = nfs.server
    path: str = nfs.path
    logger.info(
        "Transit NFS discovered from PV %s: server=%s path=%s",
        pv_name, server, path,
    )
    return server, path


def clear_cache() -> None:
    """Reset the in-process cache. Used by tests."""
    global _CACHE
    _CACHE = None
