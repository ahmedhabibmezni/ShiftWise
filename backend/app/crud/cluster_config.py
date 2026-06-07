"""
CRUD de la configuration de connexion cluster (feature 002).

SEUL module autorisé à lire/écrire les colonnes ``*_ciphertext`` : le
chiffrement/déchiffrement passe par le vault Fernet existant
(``app.services.credentials.get_vault``). Tout accès direct au ciphertext
ailleurs est un bug (même règle que le vault hyperviseur).

Chaque écriture de configuration émet une ligne d'audit append-only via
``_safe_emit_event`` (SAVEPOINT isolé — un échec d'émission ne corrompt pas
la transaction métier).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.cluster_config import (
    ClusterConnectionConfig,
    ClusterConfigEvent,
    ClusterScopeType,
    ClusterMode,
    ClusterHealthStatus,
)
from app.schemas.cluster_config import ClusterConfigUpsert
from app.services.credentials import get_vault

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def get_platform_default(db: Session) -> Optional[ClusterConnectionConfig]:
    """Retourne la ligne défaut plateforme, ou None si non configurée."""
    return (
        db.query(ClusterConnectionConfig)
        .filter(
            ClusterConnectionConfig.scope_type == ClusterScopeType.PLATFORM_DEFAULT
        )
        .first()
    )


def get_tenant_config(
    db: Session, tenant_id: str
) -> Optional[ClusterConnectionConfig]:
    """Retourne l'override d'un tenant, ou None s'il n'en a pas."""
    return (
        db.query(ClusterConnectionConfig)
        .filter(
            ClusterConnectionConfig.scope_type == ClusterScopeType.TENANT,
            ClusterConnectionConfig.tenant_id == tenant_id,
        )
        .first()
    )


def get_scope(
    db: Session, scope_type: ClusterScopeType, tenant_id: Optional[str]
) -> Optional[ClusterConnectionConfig]:
    """Retourne la ligne d'un scope donné."""
    if scope_type == ClusterScopeType.PLATFORM_DEFAULT:
        return get_platform_default(db)
    return get_tenant_config(db, tenant_id or "")


def list_all(db: Session) -> list[ClusterConnectionConfig]:
    """Retourne toutes les configurations (usage superuser)."""
    return db.query(ClusterConnectionConfig).all()


# ---------------------------------------------------------------------------
# Audit append-only (SAVEPOINT isolé)
# ---------------------------------------------------------------------------

def _safe_emit_event(
    db: Session,
    *,
    scope_type: ClusterScopeType,
    tenant_id: Optional[str],
    actor_user_id: Optional[int],
    target_mode: Optional[str],
    outcome: str,
    reason: Optional[str] = None,
) -> None:
    """Insère une ligne d'audit dans un SAVEPOINT isolé.

    Un échec d'insertion d'audit ne doit jamais empoisonner la transaction
    métier englobante (même contrat que ``services/audit_log.py``).
    """
    try:
        with db.begin_nested():
            db.add(
                ClusterConfigEvent(
                    config_scope_type=scope_type.value.upper(),
                    config_tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    actor_type="user" if actor_user_id else "system",
                    target_mode=target_mode,
                    outcome=outcome,
                    reason=reason,
                )
            )
    except Exception:  # NOSONAR — l'audit ne doit jamais casser le métier
        logger.exception(
            "cluster_config audit emit failed (scope=%s outcome=%s)",
            scope_type, outcome,
        )


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def _get_or_create_row(
    db: Session, scope_type: ClusterScopeType, tenant_id: Optional[str]
) -> ClusterConnectionConfig:
    """Récupère la ligne du scope ou en crée une neuve (non commitée)."""
    row = get_scope(db, scope_type, tenant_id)
    if row is None:
        row = ClusterConnectionConfig(
            scope_type=scope_type,
            tenant_id=tenant_id,
            mode=ClusterMode.KUBECONFIG,
            config_version=0,  # incrémenté à 1 au premier apply
        )
        db.add(row)
    return row


def _apply_mode_payload(
    row: ClusterConnectionConfig, data: ClusterConfigUpsert
) -> None:
    """Applique le mode + la charge utile non-kubeconfig (custom/in-cluster).

    Nettoie les champs des autres modes pour éviter une config incohérente.
    """
    row.mode = data.mode
    row.default_namespace = data.default_namespace
    row.verify_ssl = data.verify_ssl

    if data.mode == ClusterMode.CUSTOM:
        row.api_url = data.api_url
        if data.token:
            vault = get_vault()
            row.token_ciphertext = vault.encrypt(data.token)
            row.credential_key_version = vault.key_version
            row.credentials_updated_at = vault.now_utc()
    else:
        # Modes kubeconfig / in-cluster : pas d'URL/token custom.
        row.api_url = None
        row.token_ciphertext = None

    if data.mode != ClusterMode.KUBECONFIG:
        row.kubeconfig_ciphertext = None


def upsert(
    db: Session,
    *,
    scope_type: ClusterScopeType,
    tenant_id: Optional[str],
    data: ClusterConfigUpsert,
    actor_user_id: Optional[int],
) -> ClusterConnectionConfig:
    """Crée/met à jour la config d'un scope (hors upload kubeconfig).

    Chiffre le token custom, incrémente ``config_version`` (signal
    d'invalidation), commit, puis émet l'audit ``applied``.
    """
    row = _get_or_create_row(db, scope_type, tenant_id)
    _apply_mode_payload(row, data)
    row.config_version = (row.config_version or 0) + 1
    row.updated_by_user_id = actor_user_id
    row.health_status = ClusterHealthStatus.UNKNOWN

    db.commit()
    db.refresh(row)

    _safe_emit_event(
        db,
        scope_type=scope_type,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        target_mode=data.mode.value,
        outcome="applied",
    )
    db.commit()
    return row


def set_kubeconfig(
    db: Session,
    *,
    scope_type: ClusterScopeType,
    tenant_id: Optional[str],
    raw_bytes: bytes,
    actor_user_id: Optional[int],
    default_namespace: Optional[str] = None,
) -> ClusterConnectionConfig:
    """Stocke un kubeconfig (chiffré), force ``mode=KUBECONFIG``, bump version.

    Le contenu en clair n'est jamais persisté ni journalisé — seul le
    ciphertext Fernet l'est.
    """
    row = _get_or_create_row(db, scope_type, tenant_id)
    vault = get_vault()
    row.mode = ClusterMode.KUBECONFIG
    row.kubeconfig_ciphertext = vault.encrypt(raw_bytes.decode("utf-8"))
    row.credential_key_version = vault.key_version
    row.credentials_updated_at = vault.now_utc()
    # Un kubeconfig porte ses propres credentials → pas d'URL/token custom.
    row.api_url = None
    row.token_ciphertext = None
    if default_namespace:
        row.default_namespace = default_namespace
    row.config_version = (row.config_version or 0) + 1
    row.updated_by_user_id = actor_user_id
    row.health_status = ClusterHealthStatus.UNKNOWN

    db.commit()
    db.refresh(row)

    _safe_emit_event(
        db,
        scope_type=scope_type,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        target_mode=ClusterMode.KUBECONFIG.value,
        outcome="applied",
    )
    db.commit()
    return row


def delete_tenant_override(
    db: Session, tenant_id: str, actor_user_id: Optional[int]
) -> bool:
    """Supprime l'override d'un tenant → retombe sur le défaut plateforme.

    Retourne True si une ligne a été supprimée, False si aucune n'existait.
    """
    row = get_tenant_config(db, tenant_id)
    if row is None:
        return False

    db.delete(row)
    db.commit()

    _safe_emit_event(
        db,
        scope_type=ClusterScopeType.TENANT,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        target_mode=None,
        outcome="applied",
        reason="tenant override cleared; reverted to platform default",
    )
    db.commit()
    return True


def record_health(
    db: Session,
    cfg: ClusterConnectionConfig,
    status: ClusterHealthStatus,
    reason: Optional[str],
) -> None:
    """Met à jour les champs de santé uniquement — PAS de bump de version,
    PAS d'audit ``applied`` (ce n'est pas un changement de configuration)."""
    cfg.health_status = status
    cfg.health_reason = reason
    cfg.health_checked_at = get_vault().now_utc()
    db.commit()


# ---------------------------------------------------------------------------
# Déchiffrement (réservé au resolver / aux constructeurs de client)
# ---------------------------------------------------------------------------

def decrypt_kubeconfig(cfg: ClusterConnectionConfig) -> Optional[str]:
    """Retourne le kubeconfig en clair, ou None s'il n'y en a pas."""
    if not cfg.kubeconfig_ciphertext:
        return None
    return get_vault().decrypt(cfg.kubeconfig_ciphertext)


def decrypt_token(cfg: ClusterConnectionConfig) -> Optional[str]:
    """Retourne le bearer token en clair, ou None s'il n'y en a pas."""
    if not cfg.token_ciphertext:
        return None
    return get_vault().decrypt(cfg.token_ciphertext)


# ---------------------------------------------------------------------------
# Amorçage depuis l'environnement (R10 — cutover sans interruption)
# ---------------------------------------------------------------------------

def seed_platform_default_from_env(db: Session) -> Optional[ClusterConnectionConfig]:
    """Crée la ligne défaut plateforme depuis les variables d'environnement
    si elle n'existe pas encore (idempotent).

    Préserve le comportement actuel au premier démarrage : les ``KUBERNETES_*``
    deviennent un simple fallback d'amorçage une fois la ligne créée.
    """
    if get_platform_default(db) is not None:
        return None

    mode = _env_mode()
    row = ClusterConnectionConfig(
        scope_type=ClusterScopeType.PLATFORM_DEFAULT,
        tenant_id=None,
        mode=mode,
        default_namespace=settings.KUBERNETES_DEFAULT_NAMESPACE or "default",
        verify_ssl=bool(settings.KUBERNETES_VERIFY_SSL),
        config_version=1,
        health_status=ClusterHealthStatus.UNKNOWN,
    )

    vault = get_vault()
    if mode == ClusterMode.KUBECONFIG:
        contents = _read_env_kubeconfig()
        if contents:
            row.kubeconfig_ciphertext = vault.encrypt(contents)
            row.credential_key_version = vault.key_version
            row.credentials_updated_at = vault.now_utc()
    elif mode == ClusterMode.CUSTOM and settings.KUBERNETES_TOKEN:
        row.api_url = settings.KUBERNETES_API_URL
        row.token_ciphertext = vault.encrypt(settings.KUBERNETES_TOKEN)
        row.credential_key_version = vault.key_version
        row.credentials_updated_at = vault.now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("seeded platform-default cluster config from env (mode=%s)", mode.value)
    return row


def _env_mode() -> ClusterMode:
    """Déduit le ClusterMode depuis settings (in-cluster prioritaire)."""
    if settings.USE_IN_CLUSTER:
        return ClusterMode.INCLUSTER
    if settings.KUBERNETES_MODE == "custom":
        return ClusterMode.CUSTOM
    return ClusterMode.KUBECONFIG


def _read_env_kubeconfig() -> Optional[str]:
    """Lit le fichier kubeconfig pointé par settings, si présent."""
    raw_path = settings.KUBECONFIG_PATH
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        # backend/ — deux niveaux au-dessus de app/crud/
        path = Path(__file__).resolve().parent.parent.parent / raw_path
    if not path.exists():
        logger.warning("env kubeconfig not found at %s; platform default left without credentials", path)
        return None
    return path.read_text(encoding="utf-8")
