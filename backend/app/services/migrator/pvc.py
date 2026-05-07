"""
Target PVC provisioning in tenant namespaces.

Why a helper here and not in kubevirt_client? PVC creation is a CoreV1
operation (not KubeVirt-specific) and the migrator owns the naming
convention + sizing logic. Keeping it next to the rest of the migrator
makes the module self-contained.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.core.kubevirt_client import get_kubevirt_client
from app.services.migrator.errors import MigratorError

logger = logging.getLogger(__name__)


# Headroom on top of the converter's output_size_bytes — qemu-img convert
# inflates a sparse qcow2 to its full virtual size when written as raw, and
# we want a safety margin for filesystem metadata + KubeVirt's own padding
# (the VirtualMachine spec adds ~10% via volume.expand() heuristics).
_PVC_SIZE_HEADROOM_PCT = 15
_PVC_MIN_SIZE_BYTES = 1 * 1024 * 1024 * 1024   # never request < 1 GiB


def target_pvc_name(migration_id: int, disk_index: int) -> str:
    """Stable PVC name. Idempotent — re-running the migrator returns same name."""
    return f"shiftwise-mig-{int(migration_id)}-disk-{int(disk_index)}"


def compute_pvc_size_bytes(output_size_bytes: Optional[int]) -> int:
    """Compute the target PVC size from the converter's output size."""
    if not output_size_bytes or output_size_bytes <= 0:
        return _PVC_MIN_SIZE_BYTES
    sized = int(output_size_bytes * (100 + _PVC_SIZE_HEADROOM_PCT) / 100)
    return max(sized, _PVC_MIN_SIZE_BYTES)


def create_target_pvc(
    *,
    namespace: str,
    name: str,
    size_bytes: int,
    storage_class: str,
    labels: Optional[dict[str, str]] = None,
) -> dict:
    """Create the target PVC in the tenant namespace. Idempotent on AlreadyExists.

    Returns the PVC dict (newly created or pre-existing).
    """
    kv = get_kubevirt_client()
    body = k8s_client.V1PersistentVolumeClaim(
        metadata=k8s_client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels or {},
        ),
        spec=k8s_client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=storage_class,
            volume_mode="Filesystem",
            resources=k8s_client.V1ResourceRequirements(
                requests={"storage": str(int(size_bytes))},
            ),
        ),
    )
    try:
        pvc = kv.core_api.create_namespaced_persistent_volume_claim(
            namespace=namespace, body=body,
        )
        logger.info("Created PVC %s/%s (%d bytes, sc=%s)",
                    namespace, name, size_bytes, storage_class)
        return pvc.to_dict()
    except ApiException as e:
        if e.status == 409:
            logger.info("PVC %s/%s already exists — reusing", namespace, name)
            existing = kv.core_api.read_namespaced_persistent_volume_claim(
                name=name, namespace=namespace,
            )
            return existing.to_dict()
        if e.status in (401, 403):
            raise MigratorError(
                "ERR_MIG_NAMESPACE_FORBIDDEN",
                f"Worker SA cannot create PVCs in {namespace!r}: {e}",
                cause=e,
            ) from e
        raise MigratorError(
            "ERR_MIG_K8S_TIMEOUT",
            f"K8s refused PVC {namespace}/{name}: {e}",
            cause=e,
        ) from e


def wait_for_pvc_bound(
    *,
    namespace: str,
    name: str,
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 3.0,
) -> None:
    """Block until the PVC reaches phase=Bound.

    Some storage classes (volumeBindingMode=WaitForFirstConsumer, like
    nfs-client typically) only bind once a pod consumes them — in that
    case Bound only happens when the populator pod starts. Callers that
    will use WaitForFirstConsumer should skip this and let the populator
    Job's PVC reference trigger the binding.
    """
    kv = get_kubevirt_client()
    start = time.monotonic()
    while True:
        try:
            pvc = kv.core_api.read_namespaced_persistent_volume_claim(
                name=name, namespace=namespace,
            )
        except ApiException as e:
            raise MigratorError(
                "ERR_MIG_K8S_TIMEOUT",
                f"Could not read PVC {namespace}/{name}: {e}",
                cause=e,
            ) from e

        phase = pvc.status.phase if pvc.status else None
        if phase == "Bound":
            return
        if phase == "Lost":
            raise MigratorError(
                "ERR_MIG_PVC_PROVISIONING",
                f"PVC {namespace}/{name} entered Lost phase",
            )
        if (time.monotonic() - start) > timeout_seconds:
            raise MigratorError(
                "ERR_MIG_PVC_PROVISIONING",
                f"PVC {namespace}/{name} not Bound after {timeout_seconds}s "
                f"(phase={phase})",
            )
        time.sleep(poll_interval_seconds)


def delete_pvc(*, namespace: str, name: str) -> None:
    """Best-effort delete (used by rollback). Swallows 404."""
    kv = get_kubevirt_client()
    try:
        kv.core_api.delete_namespaced_persistent_volume_claim(
            name=name, namespace=namespace,
        )
        logger.info("Deleted PVC %s/%s", namespace, name)
    except ApiException as e:
        if e.status != 404:
            logger.warning("Could not delete PVC %s/%s: %s", namespace, name, e)
