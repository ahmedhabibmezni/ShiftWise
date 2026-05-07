"""
Tenant namespace lifecycle helper.

Each tenant maps to an OpenShift namespace `shiftwise-{tenant_id}`.
`ensure_tenant_namespace` creates that namespace (with standard labels)
if it does not already exist, and is a no-op if it does.

The function is called at the start of every MigratorService.run() call
so operators never need to create tenant namespaces manually.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.migrator.errors import MigratorError

if TYPE_CHECKING:
    from app.core.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

_LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
_LABEL_TENANT = "app.shiftwise.io/tenant"
_LABEL_PURPOSE = "app.shiftwise.io/purpose"


def _raise_classified(e: ApiException, action: str, name: str) -> NoReturn:
    """Map a kubernetes ApiException to the correct typed MigratorError.

    401/403 → NAMESPACE_FORBIDDEN (configurable, op needs to fix RBAC).
    408/5xx → K8S_TIMEOUT (transient, orchestrator may retry).
    other   → INTERNAL (permanent, fail loudly).

    Avoids the previous footgun where a 503 from the API server was
    reported as "grant the worker SA namespaces/get" and marked
    non-retryable.
    """
    status = e.status
    if status in (401, 403):
        raise MigratorError(
            "ERR_MIG_NAMESPACE_FORBIDDEN",
            f"Cannot {action} namespace {name!r}: HTTP {status} — "
            f"grant the worker SA namespaces/{action}.",
            cause=e,
        ) from e
    if status == 408 or (status is not None and status >= 500):
        raise MigratorError(
            "ERR_MIG_K8S_TIMEOUT",
            f"Kubernetes API returned HTTP {status} while trying to "
            f"{action} namespace {name!r} — transient, retryable.",
            cause=e,
        ) from e
    raise MigratorError(
        "ERR_MIG_INTERNAL",
        f"Unexpected error while trying to {action} namespace "
        f"{name!r}: HTTP {status}",
        cause=e,
    ) from e


def ensure_tenant_namespace(
    kv_client: "KubeVirtClient",
    name: str,
    tenant_id: str,
) -> None:
    """Create the tenant namespace if absent. Idempotent.

    Args:
        kv_client: Initialised KubeVirtClient (carries the API clients).
        name:      Full namespace name, e.g. ``shiftwise-nextstep``.
        tenant_id: Tenant identifier, stored in the namespace label.

    Raises:
        MigratorError: classified by HTTP status — see ``_raise_classified``.
    """
    try:
        kv_client.core_api.read_namespace(name=name)
        logger.debug("Tenant namespace %r already exists", name)
        return
    except ApiException as e:
        if e.status != 404:
            _raise_classified(e, action="get", name=name)
        # 404 — fall through to create

    labels = {
        _LABEL_MANAGED_BY: "shiftwise",
        _LABEL_TENANT: tenant_id,
        _LABEL_PURPOSE: "tenant-workload",
    }
    ns_body = k8s_client.V1Namespace(
        metadata=k8s_client.V1ObjectMeta(name=name, labels=labels),
    )
    try:
        kv_client.core_api.create_namespace(body=ns_body)
        logger.info("Created tenant namespace %r (tenant=%s)", name, tenant_id)
    except ApiException as e:
        if e.status == 409:
            # Race: another worker created it between our read and write.
            logger.debug("Tenant namespace %r created concurrently — OK", name)
            return
        _raise_classified(e, action="create", name=name)
