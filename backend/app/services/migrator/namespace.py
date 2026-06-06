"""
Tenant namespace lifecycle helper.

Each tenant maps to an OpenShift namespace `shiftwise-{tenant_id}`.
`ensure_tenant_namespace` creates that namespace (with standard labels)
if it does not already exist, and is a no-op if it does. It additionally
applies a default ResourceQuota when any quota dimension is configured
in `settings`. The quota application is idempotent — re-running against
an already-quotaed namespace is a cheap GET + skip.

The function is called at the start of every MigratorService.run() call
so operators never need to create tenant namespaces manually.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.services.migrator.errors import MigratorError

if TYPE_CHECKING:
    from app.core.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

_LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
_LABEL_TENANT = "app.shiftwise.io/tenant"
_LABEL_PURPOSE = "app.shiftwise.io/purpose"

# The populator/adapter Jobs mount the transit NFS via a built-in ``nfs``
# volume, which no stock SCC allows except ``privileged``. The custom
# ``shiftwise-populator`` SCC (openshift/base/populator-scc.yaml) clones
# restricted-v2 + ``nfs``, and is bound to a DEDICATED SA (never ``default``)
# so the privileged-nfs grant has a tight blast radius. The committed SCC only
# lists the control-plane SA (``shiftwise:shiftwise-populator``); each tenant
# namespace needs its own SA provisioned + added to the SCC users at runtime
# (see the populator-scc.yaml header note). That is what
# ``ensure_populator_scc`` does.
_POPULATOR_SCC = "shiftwise-populator"
_POPULATOR_SA = "shiftwise-populator"
_SCC_GROUP = "security.openshift.io"
_SCC_VERSION = "v1"
_SCC_PLURAL = "securitycontextconstraints"

# Single quota object per tenant namespace. Fixed name so an operator
# tweaking quotas by hand can find it in one place.
_QUOTA_NAME = "shiftwise-default-quota"


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


def _build_quota_spec() -> dict[str, str]:
    """Translate the MIGRATOR_QUOTA_* settings into a `hard` dict.

    Only populated dimensions appear in the dict — empty strings mean
    "no limit on this dimension". Returns an empty dict when no
    dimension is configured (caller then skips the quota apply).
    """
    candidates = {
        "requests.cpu": settings.MIGRATOR_QUOTA_REQUESTS_CPU,
        "requests.memory": settings.MIGRATOR_QUOTA_REQUESTS_MEMORY,
        "limits.cpu": settings.MIGRATOR_QUOTA_LIMITS_CPU,
        "limits.memory": settings.MIGRATOR_QUOTA_LIMITS_MEMORY,
        "requests.storage": settings.MIGRATOR_QUOTA_REQUESTS_STORAGE,
        "persistentvolumeclaims": settings.MIGRATOR_QUOTA_PVC_COUNT,
        "pods": settings.MIGRATOR_QUOTA_POD_COUNT,
    }
    return {key: value for key, value in candidates.items() if value}


def apply_default_resource_quota(
    kv_client: "KubeVirtClient",
    namespace: str,
    tenant_id: str,
) -> None:
    """Idempotently apply ``shiftwise-default-quota`` to the namespace.

    Skips entirely when no MIGRATOR_QUOTA_* dimension is configured —
    keeps backwards compatibility with deployments that did not opt in
    to per-tenant quotas (the previous behaviour).

    Idempotency strategy: GET first, skip if already present. Mirrors
    the namespace flow above and avoids relying on 409-on-create as a
    success signal (which makes logs noisier).
    """
    hard = _build_quota_spec()
    if not hard:
        logger.debug(
            "No MIGRATOR_QUOTA_* dimension configured — skipping quota for %r",
            namespace,
        )
        return

    try:
        kv_client.core_api.read_namespaced_resource_quota(
            name=_QUOTA_NAME, namespace=namespace
        )
        logger.debug(
            "ResourceQuota %r already exists in %r — leaving untouched",
            _QUOTA_NAME, namespace,
        )
        return
    except ApiException as e:
        if e.status != 404:
            _raise_classified(e, action="get-quota", name=namespace)
        # 404 — fall through to create

    labels = {
        _LABEL_MANAGED_BY: "shiftwise",
        _LABEL_TENANT: tenant_id,
    }
    quota_body = k8s_client.V1ResourceQuota(
        metadata=k8s_client.V1ObjectMeta(name=_QUOTA_NAME, labels=labels),
        spec=k8s_client.V1ResourceQuotaSpec(hard=hard),
    )
    try:
        kv_client.core_api.create_namespaced_resource_quota(
            namespace=namespace, body=quota_body
        )
        logger.info(
            "Applied default ResourceQuota to %r (tenant=%s, dimensions=%s)",
            namespace, tenant_id, sorted(hard.keys()),
        )
    except ApiException as e:
        if e.status == 409:
            # Race: another worker beat us to the create. The peer
            # presumably wrote the same body — accept and move on.
            logger.debug(
                "ResourceQuota %r in %r created concurrently — OK",
                _QUOTA_NAME, namespace,
            )
            return
        _raise_classified(e, action="create-quota", name=namespace)


def ensure_populator_scc(kv_client: "KubeVirtClient", namespace: str) -> None:
    """Provision the dedicated populator SA in ``namespace`` and grant it the
    ``shiftwise-populator`` SCC (which permits the direct ``nfs`` volume the
    adapter/populator Jobs mount).

    Idempotent: the SA create swallows 409, and the SCC ``users`` list is only
    patched when the tenant SA is absent from it. Without this the adapter pod
    in a freshly auto-created tenant namespace is rejected by SCC admission
    (``nfs volumes are not allowed``).
    """
    sa_body = k8s_client.V1ServiceAccount(
        metadata=k8s_client.V1ObjectMeta(
            name=_POPULATOR_SA,
            labels={_LABEL_MANAGED_BY: "shiftwise"},
        ),
    )
    try:
        kv_client.core_api.create_namespaced_service_account(namespace, sa_body)
        logger.info("Created populator SA %r in %r", _POPULATOR_SA, namespace)
    except ApiException as e:
        if e.status != 409:
            _raise_classified(e, action="create-sa", name=namespace)

    sa_user = f"system:serviceaccount:{namespace}:{_POPULATOR_SA}"
    try:
        scc = kv_client.api.get_cluster_custom_object(
            _SCC_GROUP, _SCC_VERSION, _SCC_PLURAL, _POPULATOR_SCC,
        )
        users = list(scc.get("users") or [])
        if sa_user not in users:
            users.append(sa_user)
            kv_client.api.patch_cluster_custom_object(
                _SCC_GROUP, _SCC_VERSION, _SCC_PLURAL, _POPULATOR_SCC,
                {"users": users},
            )
            logger.info("Granted SCC %r to %r", _POPULATOR_SCC, sa_user)
    except ApiException as e:
        _raise_classified(e, action="grant-scc", name=namespace)


def ensure_tenant_namespace(
    kv_client: "KubeVirtClient",
    name: str,
    tenant_id: str,
) -> None:
    """Create the tenant namespace if absent and apply its default quota.

    Both calls are idempotent so an existing tenant namespace (created
    before quotas were configured) gets retroactively quotaed on the
    next migration — no separate migration needed.

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
        apply_default_resource_quota(kv_client, name, tenant_id)
        ensure_populator_scc(kv_client, name)
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
            apply_default_resource_quota(kv_client, name, tenant_id)
            ensure_populator_scc(kv_client, name)
            return
        _raise_classified(e, action="create", name=name)

    apply_default_resource_quota(kv_client, name, tenant_id)
    ensure_populator_scc(kv_client, name)
