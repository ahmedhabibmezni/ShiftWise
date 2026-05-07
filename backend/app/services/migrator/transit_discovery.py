"""
Transit NFS auto-discovery.

Reads the PV backing `transit-pvc` in the converter namespace at runtime
so that MIGRATOR_NFS_SERVER / MIGRATOR_NFS_PATH env vars don't have to be
set manually per deployment.

Cache: result is stored in a module-level tuple so each worker process only
hits the API once.  The cached value is valid for the lifetime of the worker
pod — the PV / NFS server never changes without a redeployment.

Thread-safety: the cache write is guarded by a lock with a double-check
pattern. Necessary because Celery workers can run with --pool=threads or
--pool=gevent and two threads racing on a cold cache would otherwise both
hit the API and store inconsistent state.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, NoReturn

from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.services.migrator.errors import MigratorError

if TYPE_CHECKING:
    from app.core.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

# Module-level cache — (server, path) or None when not yet discovered.
_CACHE: tuple[str, str] | None = None
_CACHE_LOCK = threading.Lock()


def _raise_classified(
    e: ApiException, *, action: str, resource: str, rbac_hint: str,
) -> NoReturn:
    """Map a kubernetes ApiException to the correct typed MigratorError.

    Mirrors namespace._raise_classified but uses ERR_MIG_INTERNAL for the
    forbidden case — there is no dedicated catalog code for "PV/PVC read
    forbidden", and bundling them under NAMESPACE_FORBIDDEN would be
    misleading.
    """
    status = e.status
    if status in (401, 403):
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"Cannot {action} {resource}: HTTP {status} — {rbac_hint}",
            cause=e,
        ) from e
    if status == 408 or (status is not None and status >= 500):
        raise MigratorError(
            "ERR_MIG_K8S_TIMEOUT",
            f"Kubernetes API returned HTTP {status} while trying to "
            f"{action} {resource} — transient, retryable.",
            cause=e,
        ) from e
    raise MigratorError(
        "ERR_MIG_INTERNAL",
        f"Unexpected error while trying to {action} {resource}: "
        f"HTTP {status}",
        cause=e,
    ) from e


def discover_transit_nfs(kv_client: "KubeVirtClient") -> tuple[str, str]:
    """Return (nfs_server, nfs_path) for the transit PVC.

    Resolution order:
      1. Explicit env vars (MIGRATOR_NFS_SERVER + MIGRATOR_NFS_PATH both set)
      2. In-process cache (from a previous call this worker lifetime)
      3. Live lookup: PVC → PV → spec.nfs

    Raises MigratorError if discovery fails and no explicit config is set.
    """
    server = settings.MIGRATOR_NFS_SERVER
    path = settings.MIGRATOR_NFS_PATH

    if server and path:
        return server, path

    # Partial override is almost always a config typo — warn loudly.
    # We still fall back to auto-discovery so the migration doesn't hard-fail
    # on an admin oversight, but the warning makes the cause obvious in logs.
    if bool(server) != bool(path):
        logger.warning(
            "Partial MIGRATOR_NFS_* override detected "
            "(MIGRATOR_NFS_SERVER=%r, MIGRATOR_NFS_PATH=%r). Both must be "
            "set together to bypass auto-discovery. Falling back to live "
            "PV lookup — fix your env vars or unset both.",
            server, path,
        )

    if _CACHE is not None:
        return _CACHE

    with _CACHE_LOCK:
        # Double-check: another thread may have populated the cache while
        # we waited on the lock.
        if _CACHE is not None:
            return _CACHE
        result = _lookup_from_cluster(kv_client)
        # Module-level rebind under the lock.
        globals()["_CACHE"] = result
        return result


def _lookup_from_cluster(kv_client: "KubeVirtClient") -> tuple[str, str]:
    pvc_namespace = settings.CONVERTER_K8S_NAMESPACE
    pvc_name = settings.CONVERTER_TRANSIT_PVC

    # Step 1: read the PVC to get the bound PV name.
    try:
        pvc = kv_client.get_pvc(name=pvc_name, namespace=pvc_namespace)
    except ApiException as e:
        _raise_classified(
            e,
            action="read",
            resource=f"transit PVC {pvc_namespace}/{pvc_name}",
            rbac_hint=(
                f"set MIGRATOR_NFS_SERVER + MIGRATOR_NFS_PATH or grant "
                f"the worker SA pvc/get on {pvc_namespace!r}."
            ),
        )

    pv_name: str | None = None
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
        _raise_classified(
            e,
            action="read",
            resource=f"PersistentVolume {pv_name!r}",
            rbac_hint="grant the worker SA pv/get.",
        )

    nfs = pv.spec.nfs if pv.spec else None
    if nfs is None or not nfs.server or not nfs.path:
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"PV {pv_name!r} has no spec.nfs section "
            f"(server={getattr(nfs, 'server', None)!r}, "
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
    with _CACHE_LOCK:
        _CACHE = None
