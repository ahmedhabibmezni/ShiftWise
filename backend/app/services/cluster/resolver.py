"""
Résolution de la configuration cluster effective + cache de clients (R1).

``get_client_for_tenant(db, tenant_id)`` résout la configuration effective
(ligne tenant → ligne défaut plateforme → amorçage env) et retourne un
``KubeVirtClient`` mis en cache par ``(scope_key, config_version)``. Sur
dérive de ``config_version`` (un autre process a sauvegardé), le prochain
``resolve`` reconstruit le client — pas de redémarrage, pas d'IPC.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session
from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.core.kubevirt_client import KubeVirtClient, get_kubevirt_client
from app.crud import cluster_config as crud_cluster
from app.models.cluster_config import (
    ClusterConnectionConfig,
    ClusterScopeType,
    ClusterMode,
    ClusterHealthStatus,
)
from app.schemas.cluster_config import ConnectionTestResult

logger = logging.getLogger(__name__)

# Cache process-local : scope_key -> (config_version, client).
_client_cache: Dict[str, Tuple[int, KubeVirtClient]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Résolution
# ---------------------------------------------------------------------------

def resolve_effective_config(
    db: Session, tenant_id: Optional[str]
) -> Optional[ClusterConnectionConfig]:
    """Retourne la configuration effective pour un tenant.

    Ordre : override tenant → défaut plateforme → None (amorçage env).
    """
    if tenant_id:
        row = crud_cluster.get_tenant_config(db, tenant_id)
        if row is not None:
            return row
    return crud_cluster.get_platform_default(db)


def _spec_from_config(cfg: ClusterConnectionConfig) -> Dict[str, Any]:
    """Convertit une ligne ORM en spec de construction (déchiffre les secrets)."""
    return {
        "mode": cfg.mode.value,
        "kubeconfig_str": crud_cluster.decrypt_kubeconfig(cfg),
        "api_url": cfg.api_url,
        "token": crud_cluster.decrypt_token(cfg),
        "verify_ssl": bool(cfg.verify_ssl),
    }


def get_client_for_tenant(
    db: Session, tenant_id: Optional[str] = None
) -> KubeVirtClient:
    """Retourne un ``KubeVirtClient`` pour la config effective d'un tenant.

    Sans ligne en base, retombe sur le client d'amorçage basé sur
    l'environnement (compatibilité ascendante).
    """
    cfg = resolve_effective_config(db, tenant_id)
    if cfg is None:
        logger.debug("no cluster config row; using env bootstrap client")
        return get_kubevirt_client()

    scope_key = cfg.scope_key
    version = cfg.config_version
    with _cache_lock:
        cached = _client_cache.get(scope_key)
        if cached is not None and cached[0] == version:
            return cached[1]
        client = KubeVirtClient(config_spec=_spec_from_config(cfg))
        _client_cache[scope_key] = (version, client)
        return client


def invalidate_scope(scope_key: str) -> None:
    """Évince le client mis en cache pour un scope (après un apply local)."""
    with _cache_lock:
        _client_cache.pop(scope_key, None)


# ---------------------------------------------------------------------------
# Sonde de connectivité (R6)
# ---------------------------------------------------------------------------

def run_connection_test(
    db: Session,
    scope_type: ClusterScopeType,
    tenant_id: Optional[str],
) -> ConnectionTestResult:
    """Sonde live bornée contre la config stockée d'un scope.

    Construit un client jetable, effectue une lecture bornée (list namespaces)
    et classe le résultat. Met à jour les champs ``health_*`` (pas de bump de
    version). Retourne toujours un résultat — l'échec est dans le corps, pas en
    HTTP.
    """
    cfg = crud_cluster.get_scope(db, scope_type, tenant_id)
    if cfg is None and tenant_id:
        # Pas de config propre — teste le défaut plateforme effectif.
        cfg = crud_cluster.get_platform_default(db)
    if cfg is None:
        return ConnectionTestResult(
            status=ClusterHealthStatus.INVALID,
            reason="no cluster configuration to test",
        )

    result = _probe(cfg)
    crud_cluster.record_health(db, cfg, result.status, result.reason)
    return result


def _probe(cfg: ClusterConnectionConfig) -> ConnectionTestResult:
    """Construit un client jetable et tente une lecture bornée classifiée."""
    timeout = settings.CLUSTER_CONNECTION_TEST_TIMEOUT_SECONDS
    try:
        if cfg.mode == ClusterMode.INCLUSTER:
            client = KubeVirtClient(config_spec={"mode": "incluster"})
        else:
            client = KubeVirtClient(config_spec=_spec_from_config(cfg))
    except Exception as exc:  # NOSONAR — construction du client = config invalide
        return ConnectionTestResult(
            status=ClusterHealthStatus.INVALID,
            reason=f"invalid configuration: {type(exc).__name__}: {exc}",
        )

    try:
        ns = client.core_api.list_namespace(_request_timeout=timeout)
        count = len(getattr(ns, "items", []) or [])
    except ApiException as exc:
        return _classify_api_exception(exc)
    except Exception as exc:  # NOSONAR — transport/TLS/DNS classés ci-dessous
        return _classify_transport_error(exc)

    # Cluster joignable — on enrichit au mieux. Chaque détail est best-effort :
    # une lecture refusée (RBAC) ou absente ne doit PAS dégrader le statut.
    server_version, platform = _probe_version(client, timeout)
    node_count = _probe_node_count(client, timeout)
    return ConnectionTestResult(
        status=ClusterHealthStatus.HEALTHY,
        reason="cluster reachable",
        server_version=server_version,
        platform=platform,
        namespace_count=count,
        node_count=node_count,
        api_url=_client_host(client),
    )


def _probe_version(client: KubeVirtClient, timeout: int) -> Tuple[Optional[str], Optional[str]]:
    """Retourne (gitVersion, plateforme) du serveur API — best-effort."""
    try:
        from kubernetes import client as k8s_client

        code = k8s_client.VersionApi(client._api_client).get_code(
            _request_timeout=timeout,
        )
        git = getattr(code, "git_version", None)
        platform = getattr(code, "platform", None)
        # Ne renvoyer que des chaînes — un client mocké/atypique ne doit pas
        # injecter un type invalide dans la réponse (robustesse + testabilité).
        return (
            git if isinstance(git, str) else None,
            platform if isinstance(platform, str) else None,
        )
    except Exception:  # NOSONAR — détail facultatif, ne dégrade pas le statut
        logger.debug("cluster version probe failed", exc_info=True)
        return None, None


def _probe_node_count(client: KubeVirtClient, timeout: int) -> Optional[int]:
    """Retourne le nombre de nœuds — best-effort (RBAC peut l'interdire)."""
    try:
        nodes = client.core_api.list_node(_request_timeout=timeout)
        return len(getattr(nodes, "items", []) or [])
    except Exception:  # NOSONAR — détail facultatif, ne dégrade pas le statut
        logger.debug("cluster node probe failed", exc_info=True)
        return None


def _client_host(client: KubeVirtClient) -> Optional[str]:
    """Extrait l'URL de l'API server du client construit (best-effort)."""
    try:
        host = client._api_client.configuration.host
        return host if isinstance(host, str) else None
    except Exception:  # NOSONAR
        return None


def _classify_api_exception(exc: ApiException) -> ConnectionTestResult:
    """401/403 → auth-failed ; 408/5xx → unreachable ; autre → degraded."""
    status_code = getattr(exc, "status", None)
    if status_code in (401, 403):
        return ConnectionTestResult(
            status=ClusterHealthStatus.AUTH_FAILED,
            reason=f"authentication rejected (HTTP {status_code})",
        )
    if status_code == 408 or (isinstance(status_code, int) and status_code >= 500):
        return ConnectionTestResult(
            status=ClusterHealthStatus.UNREACHABLE,
            reason=f"cluster API error (HTTP {status_code})",
        )
    return ConnectionTestResult(
        status=ClusterHealthStatus.DEGRADED,
        reason=f"unexpected API response (HTTP {status_code})",
    )


def _classify_transport_error(exc: Exception) -> ConnectionTestResult:
    """Distingue une erreur TLS d'une erreur réseau générique."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if "ssl" in text or "certificate" in text or "tls" in text:
        return ConnectionTestResult(
            status=ClusterHealthStatus.UNREACHABLE,
            reason=f"TLS verification error: {exc}",
        )
    return ConnectionTestResult(
        status=ClusterHealthStatus.UNREACHABLE,
        reason=f"cluster unreachable: {exc}",
    )
