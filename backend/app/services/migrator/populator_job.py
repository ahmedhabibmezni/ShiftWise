"""
Populator Job — copies a QCOW2 from the transit NFS share to the target PVC.

The pod runs in the tenant namespace and mounts:
    - the transit NFS export read-only at /src (volumes.nfs, built-in K8s)
    - the target PVC                read-write at /dst

Command::

    qemu-img convert -p -t none -W -O raw \
        /src/{tenant_id}/outputs/{group_uuid}/{disk_index}.qcow2 \
        /dst/disk.img

We convert qcow2 -> raw on copy because:
    - KubeVirt boots faster from raw (no COW redirection at runtime)
    - virtio-blk on raw bypasses qemu's qcow2 driver in the data path
    - the copy step is "free" — we'd be reading every byte anyway

Why direct NFS volume (not a PVC) for the source side?
    The transit-pvc lives in the converter's home namespace (`shiftwise`).
    PVCs are namespace-scoped, so a populator pod running in
    `shiftwise-{tenant_id}` cannot reference it. The underlying data is on a
    single NFS export that the cluster nodes already mount; the cleanest
    way to reach it from any namespace is the K8s built-in `nfs` volume
    type, which doesn't require an in-namespace PVC. The destination side
    keeps a normal PVC because that's what KubeVirt will reference.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.core.kubevirt_client import get_kubevirt_client
from app.services.migrator.errors import MigratorError
from app.services.migrator.transit_discovery import discover_transit_nfs

logger = logging.getLogger(__name__)


_LABEL_APP = "app.shiftwise.io/component"
_LABEL_APP_VAL = "migrator-populator"
_LABEL_MIGRATION = "app.shiftwise.io/migration-id"
_LABEL_DISK = "app.shiftwise.io/disk-index"


@dataclass(frozen=True)
class PopulatorOutcome:
    succeeded: bool
    failure_reason: Optional[str]
    container_exit_code: Optional[int]


def populator_job_name(migration_id: int, disk_index: int) -> str:
    """Stable, idempotent Job name (DNS-1123 compliant, max 63 chars)."""
    return f"shiftwise-populate-{int(migration_id)}-d{int(disk_index)}"


def submit_populator_job(
    *,
    namespace: str,
    job_name: str,
    migration_id: int,
    disk_index: int,
    target_pvc_name: str,
    src_relative_path: str,
    backoff_limit: int = 0,
    active_deadline_seconds: int = 6 * 3600,
) -> str:
    """Submit the populator Job. Idempotent on AlreadyExists (returns the
    existing Job's name).
    """
    kv = get_kubevirt_client()
    nfs_server, nfs_path = discover_transit_nfs(kv)
    manifest = _build_manifest(
        namespace=namespace,
        job_name=job_name,
        migration_id=migration_id,
        disk_index=disk_index,
        target_pvc_name=target_pvc_name,
        src_relative_path=src_relative_path,
        backoff_limit=backoff_limit,
        active_deadline_seconds=active_deadline_seconds,
        nfs_server=nfs_server,
        nfs_path=nfs_path,
    )
    try:
        kv.batch_api.create_namespaced_job(namespace=namespace, body=manifest)
        logger.info("Submitted populator Job %s/%s (disk=%d)",
                    namespace, job_name, disk_index)
    except ApiException as e:
        if e.status == 409:
            logger.info("Populator Job %s/%s already exists — reusing",
                        namespace, job_name)
            return job_name
        if e.status in (401, 403):
            raise MigratorError(
                "ERR_MIG_NAMESPACE_FORBIDDEN",
                f"Worker SA cannot create Jobs in {namespace!r}: {e}",
                cause=e,
            ) from e
        raise MigratorError(
            "ERR_MIG_K8S_TIMEOUT",
            f"K8s refused populator Job {namespace}/{job_name}: {e}",
            cause=e,
        ) from e
    return job_name


def wait_for_populator(
    *,
    namespace: str,
    job_name: str,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: Optional[int] = None,
) -> PopulatorOutcome:
    """Block until the Job reaches a terminal state."""
    kv = get_kubevirt_client()
    start = time.monotonic()
    while True:
        try:
            job = kv.batch_api.read_namespaced_job_status(
                name=job_name, namespace=namespace,
            )
        except ApiException as e:
            raise MigratorError(
                "ERR_MIG_K8S_TIMEOUT",
                f"Could not read populator Job {namespace}/{job_name}: {e}",
                cause=e,
            ) from e

        status = job.status
        if status.succeeded and status.succeeded >= 1:
            return PopulatorOutcome(
                succeeded=True, failure_reason=None, container_exit_code=0,
            )
        if status.failed and status.failed >= 1:
            return PopulatorOutcome(
                succeeded=False,
                failure_reason=_extract_failure_reason(job),
                container_exit_code=_extract_exit_code(namespace, job_name),
            )

        if timeout_seconds is not None and (time.monotonic() - start) > timeout_seconds:
            return PopulatorOutcome(
                succeeded=False,
                failure_reason="TimeoutInClient",
                container_exit_code=None,
            )

        time.sleep(poll_interval_seconds)


def get_populator_logs(*, namespace: str, job_name: str) -> str:
    """Concatenate logs from all pods of the populator Job (best effort)."""
    kv = get_kubevirt_client()
    try:
        pods = kv.core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job-name={job_name}",
        )
    except ApiException as e:
        logger.warning("Could not list pods for populator %s/%s: %s",
                       namespace, job_name, e)
        return ""

    chunks: list[str] = []
    for pod in pods.items:
        try:
            log = kv.core_api.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=namespace,
                tail_lines=2000,
            )
            chunks.append(log or "")
        except ApiException as e:
            chunks.append(f"[error reading log for pod {pod.metadata.name}: {e}]")
    return "\n---\n".join(chunks)


def delete_populator(*, namespace: str, job_name: str) -> None:
    """Best-effort delete (used by rollback)."""
    from kubernetes import client as k8s_client
    kv = get_kubevirt_client()
    body = k8s_client.V1DeleteOptions(propagation_policy="Foreground")
    try:
        kv.batch_api.delete_namespaced_job(
            name=job_name, namespace=namespace, body=body,
        )
    except ApiException as e:
        if e.status != 404:
            logger.warning("Could not delete populator %s/%s: %s",
                           namespace, job_name, e)


# --- internals -------------------------------------------------------------

def _build_manifest(
    *,
    namespace: str,
    job_name: str,
    migration_id: int,
    disk_index: int,
    target_pvc_name: str,
    src_relative_path: str,
    backoff_limit: int,
    active_deadline_seconds: int,
    nfs_server: str,
    nfs_path: str,
) -> dict:
    labels = {
        _LABEL_APP: _LABEL_APP_VAL,
        _LABEL_MIGRATION: str(migration_id),
        _LABEL_DISK: str(disk_index),
    }
    src_path = f"/src/{src_relative_path.lstrip('/')}"
    dst_path = "/dst/disk.img"
    cmd = [
        "qemu-img", "convert",
        "-p",                 # progress to stderr
        "-t", "none",         # bypass page cache
        "-W",                 # write out-of-order (faster)
        "-O", "raw",
        src_path,
        dst_path,
    ]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "backoffLimit": backoff_limit,
            "activeDeadlineSeconds": active_deadline_seconds,
            "ttlSecondsAfterFinished": 24 * 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": settings.MIGRATOR_POPULATOR_SA,
                    "containers": [{
                        "name": "populator",
                        "image": settings.MIGRATOR_POPULATOR_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "command": cmd,
                        "volumeMounts": [
                            {"name": "src", "mountPath": "/src", "readOnly": True},
                            {"name": "dst", "mountPath": "/dst"},
                        ],
                        "resources": {
                            "requests": {"cpu": "200m", "memory": "256Mi"},
                            "limits":   {"cpu": "2",    "memory": "2Gi"},
                        },
                    }],
                    "volumes": [
                        # Source = NFS direct. PVCs are namespace-scoped, so
                        # the transit-pvc (converter namespace) is not
                        # reachable from the tenant namespace. volumes.nfs is
                        # the built-in K8s type that works from any namespace.
                        # Server + path are resolved at manifest build time:
                        # explicit env vars take priority, otherwise the PV
                        # backing transit-pvc is inspected at runtime.
                        {
                            "name": "src",
                            "nfs": {
                                "server": nfs_server,
                                "path": nfs_path,
                                "readOnly": True,
                            },
                        },
                        {
                            "name": "dst",
                            "persistentVolumeClaim": {
                                "claimName": target_pvc_name,
                            },
                        },
                    ],
                },
            },
        },
    }


def _extract_failure_reason(job) -> Optional[str]:
    for cond in (job.status.conditions or []):
        if cond.type == "Failed" and cond.status == "True":
            return cond.reason or cond.message
    return None


def _extract_exit_code(namespace: str, job_name: str) -> Optional[int]:
    kv = get_kubevirt_client()
    try:
        pods = kv.core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job-name={job_name}",
        )
    except ApiException:
        return None
    for pod in pods.items:
        for cs in (pod.status.container_statuses or []):
            term = cs.state.terminated if cs.state else None
            if term is not None and term.exit_code is not None:
                return int(term.exit_code)
    return None
