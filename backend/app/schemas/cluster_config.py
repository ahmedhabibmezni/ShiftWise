"""
Schémas Pydantic pour la connectivité cluster (feature 002).

Règle de non-divulgation (SC-004) : aucun secret (contenu kubeconfig, token,
clé client) n'apparaît dans un schéma de réponse. Les secrets sont
*write-only* : acceptés en entrée (``ClusterConfigUpsert.token`` / upload
multipart pour le kubeconfig), jamais renvoyés.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.cluster_config import (
    ClusterMode,
    ClusterScopeType,
    ClusterHealthStatus,
)
# Réutilise le garde SSRF existant du domaine hyperviseur (Principe II).
from app.schemas.hypervisor import _check_host_not_ssrf


class ClusterConfigRead(BaseModel):
    """Vue lecture d'une configuration de scope — SANS aucun secret."""

    scope_type: ClusterScopeType
    tenant_id: Optional[str] = None
    mode: ClusterMode
    has_credentials: bool = False
    api_url: Optional[str] = None  # non sensible (mode custom)
    verify_ssl: bool = False
    default_namespace: str = "default"
    health_status: ClusterHealthStatus = ClusterHealthStatus.UNKNOWN
    health_reason: Optional[str] = None
    health_checked_at: Optional[datetime] = None
    config_version: int = 1
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ClusterConfigScopeEntry(BaseModel):
    """Entrée de la liste des scopes.

    ``config`` est ``None`` quand le scope n'a pas de configuration propre ;
    ``using_platform_default`` est alors ``True`` (le tenant retombe sur le
    défaut plateforme).
    """

    scope_type: ClusterScopeType
    tenant_id: Optional[str] = None
    using_platform_default: bool = False
    config: Optional[ClusterConfigRead] = None

    model_config = ConfigDict(from_attributes=True)


class ClusterConfigScopeList(BaseModel):
    """Liste des scopes visibles par l'appelant."""

    items: list[ClusterConfigScopeEntry] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ClusterConfigUpsert(BaseModel):
    """Requête de création/mise à jour (hors upload kubeconfig).

    Le ``token`` est write-only (jamais relu). Le contenu kubeconfig n'arrive
    PAS par ce corps JSON mais par l'endpoint multipart dédié.
    """

    mode: ClusterMode
    api_url: Optional[str] = Field(None, max_length=512)
    token: Optional[str] = Field(None, min_length=1)  # write-only (custom)
    verify_ssl: bool = False
    default_namespace: str = Field("default", min_length=1, max_length=253)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("api_url")
    @classmethod
    def _validate_api_url_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Refuse une URL d'API custom ciblant une plage interdite (SSRF)."""
        if v is None:
            return v
        candidate = v.strip()
        if not candidate:
            raise ValueError("api_url ne doit pas être vide")
        # _check_host_not_ssrf accepte un host ou une URI (extrait l'hôte).
        _check_host_not_ssrf(candidate)
        return candidate


class ConnectionTestResult(BaseModel):
    """Résultat d'une sonde de connectivité live.

    Quand le cluster est joignable, les champs de détail (version serveur,
    plateforme, nombres de namespaces/nœuds) sont remplis au mieux — un détail
    indisponible (RBAC restreint) reste ``None`` sans dégrader le statut.
    """

    status: ClusterHealthStatus
    reason: Optional[str] = None
    server_version: Optional[str] = None
    platform: Optional[str] = None
    namespace_count: Optional[int] = None
    node_count: Optional[int] = None
    api_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
