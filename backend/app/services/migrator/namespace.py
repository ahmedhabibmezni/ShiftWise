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
from typing import TYPE_CHECKING

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.services.migrator.errors import MigratorError

if TYPE_CHECKING:
    from app.core.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

_LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
_LABEL_TENANT = "app.shiftwise.io/tenant"
_LABEL_PURPOSE = "app.shiftwise.io/purpose"


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
        MigratorError: On unexpected API errors (not 404/409).
    """
    try:
        kv_client.core_api.read_namespace(name=name)
        logger.debug("Tenant namespace %r already exists", name)
        return
    except ApiException as e:
        if e.status != 404:
            raise MigratorError(
                "ERR_MIG_NAMESPACE_FORBIDDEN",
                f"Cannot check namespace {name!r}: HTTP {e.status} — "
                f"grant the worker SA namespaces/get.",
                cause=e,
            ) from e

    # 404 — namespace does not exist, create it.
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
        raise MigratorError(
            "ERR_MIG_NAMESPACE_FORBIDDEN",
            f"Cannot create namespace {name!r}: HTTP {e.status} — "
            f"grant the worker SA namespaces/create.",
            cause=e,
        ) from e
