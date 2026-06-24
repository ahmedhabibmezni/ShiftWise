"""
Modèles Cluster Connectivity (feature 002).

Deux tables :

- ``cluster_connection_config`` — une ligne par *scope* (le défaut
  plateforme, ou un tenant). Stocke le mode de connexion Kubernetes/OpenShift
  et la charge utile chiffrée (kubeconfig / token) au repos via le vault
  Fernet existant. ``config_version`` est l'horloge monotone par ligne qui
  sert de signal d'invalidation du cache de clients (research R1).

- ``cluster_config_events`` — journal append-only des changements de
  configuration (qui / quand / quel scope / quel mode / résultat). Ne stocke
  jamais de secret. Un trigger PostgreSQL bloque UPDATE/DELETE (migration).

Conventions reprises du modèle ``Hypervisor`` : ``LargeBinary`` pour le
ciphertext, ``credential_key_version`` + ``credentials_updated_at``,
``server_default`` sur les colonnes non-nullables (Audit D16).
"""

import enum

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, LargeBinary,
    Enum as SQLEnum, ForeignKey, UniqueConstraint, CheckConstraint,
    text, false, func,
)

from app.models.base import BaseModel


class ClusterScopeType(str, enum.Enum):
    """Portée d'une configuration de connexion cluster."""
    PLATFORM_DEFAULT = "platform_default"  # défaut plateforme (superadmin)
    TENANT = "tenant"                      # override propre à un tenant


class ClusterMode(str, enum.Enum):
    """Mode de connexion Kubernetes/OpenShift."""
    KUBECONFIG = "kubeconfig"  # fichier kubeconfig (uploadé, chiffré)
    INCLUSTER = "incluster"    # ServiceAccount du pod (défaut plateforme seul)
    CUSTOM = "custom"          # API URL + bearer token (chiffré)


class ClusterHealthStatus(str, enum.Enum):
    """Dernier état de connectivité observé pour un scope."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class ClusterConnectionConfig(BaseModel):
    """Configuration de connexion cluster, scopée (plateforme ou tenant)."""

    __tablename__ = "cluster_connection_config"

    __table_args__ = (
        # Une seule ligne par scope : un défaut plateforme (tenant_id NULL) et
        # au plus une ligne par tenant.
        UniqueConstraint(
            "scope_type", "tenant_id",
            name="uq_cluster_config_scope",
        ),
        # tenant_id renseigné si et seulement si scope_type=TENANT.
        CheckConstraint(
            "(scope_type = 'PLATFORM_DEFAULT' AND tenant_id IS NULL) "
            "OR (scope_type = 'TENANT' AND tenant_id IS NOT NULL)",
            name="ck_cluster_config_scope_tenant",
        ),
        # in-cluster réservé au défaut plateforme (un pod = une identité
        # in-cluster).
        CheckConstraint(
            "mode <> 'INCLUSTER' OR scope_type = 'PLATFORM_DEFAULT'",
            name="ck_cluster_config_incluster_platform_only",
        ),
    )

    scope_type = Column(
        SQLEnum(ClusterScopeType), nullable=False, index=True,
    )
    tenant_id = Column(String(100), nullable=True, index=True)

    mode = Column(SQLEnum(ClusterMode), nullable=False)

    # Charge utile chiffrée (selon le mode). Accès UNIQUEMENT via crud.
    kubeconfig_ciphertext = Column(LargeBinary, nullable=True)
    api_url = Column(String(512), nullable=True)          # mode=custom
    token_ciphertext = Column(LargeBinary, nullable=True)  # mode=custom
    verify_ssl = Column(Boolean, nullable=False, default=False, server_default=false())
    default_namespace = Column(
        String(253), nullable=False, default="default", server_default="default",
    )

    credential_key_version = Column(
        Integer, nullable=False, default=1, server_default="1",
    )
    credentials_updated_at = Column(DateTime(timezone=True), nullable=True)

    # Horloge monotone par ligne — signal d'invalidation du cache (R1).
    config_version = Column(
        Integer, nullable=False, default=1, server_default="1",
    )

    health_status = Column(
        SQLEnum(ClusterHealthStatus), nullable=False,
        default=ClusterHealthStatus.UNKNOWN, server_default="UNKNOWN",
    )
    health_reason = Column(String(512), nullable=True)
    health_checked_at = Column(DateTime(timezone=True), nullable=True)

    updated_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    def __repr__(self) -> str:
        scope = self.tenant_id or "platform-default"
        return (
            f"<ClusterConnectionConfig(scope={scope}, mode={self.mode}, "
            f"v={self.config_version})>"
        )

    @property
    def scope_key(self) -> str:
        """Clé de cache stable : 'platform-default' ou 'tenant:{id}'."""
        if self.scope_type == ClusterScopeType.TENANT:
            return f"tenant:{self.tenant_id}"
        return "platform-default"

    @property
    def has_credentials(self) -> bool:
        """Vrai si un secret (kubeconfig ou token) est stocké pour ce scope."""
        return bool(self.kubeconfig_ciphertext or self.token_ciphertext)


class ClusterConfigEvent(BaseModel):
    """Journal append-only des changements de configuration cluster.

    Append-only garanti par un trigger PostgreSQL (cf. migration). Ne stocke
    jamais de valeur secrète — seulement des métadonnées non sensibles.
    """

    __tablename__ = "cluster_config_events"

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system')",
            name="ck_cluster_config_events_actor_type",
        ),
        CheckConstraint(
            "outcome IN ('applied', 'rejected', 'failed')",
            name="ck_cluster_config_events_outcome",
        ),
    )

    # Scope dénormalisé — survit à la suppression/réversion de la ligne config.
    config_scope_type = Column(String(20), nullable=False)
    config_tenant_id = Column(String(100), nullable=True)

    actor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    actor_type = Column(
        String(16), nullable=False, default="user", server_default="user",
    )
    target_mode = Column(String(20), nullable=True)
    outcome = Column(String(16), nullable=False)
    reason = Column(String(512), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ClusterConfigEvent(scope={self.config_scope_type}, "
            f"outcome={self.outcome})>"
        )
