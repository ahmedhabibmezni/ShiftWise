"""
ShiftWise Migration CRUD Operations

Opérations CRUD (Create, Read, Update, Delete) pour les migrations.

Toutes les fonctions prennent une session SQLAlchemy en paramètre
et retournent des objets du modèle Migration.
Filtrage multi-tenancy via tenant_id optionnel.
"""

from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEvent, MigrationEventType
from app.services.audit_log import AuditEmitter


class MigrationHasAuditTrail(Exception):
    """Levée quand une migration ne peut être supprimée car son journal
    d'audit (``migration_events``) la référence. Le journal est conservé de
    façon indépendante (FK ``ON DELETE NO ACTION`` + table append-only) ;
    mappée en HTTP 409 par la couche API."""


def get_migration(
        db: Session,
        migration_id: int,
        tenant_id: Optional[str] = None
) -> Optional[Migration]:
    """
    Recupere une migration par son ID.

    Args:
        db: Session de base de donnees
        migration_id: ID de la migration
        tenant_id: Si fourni, filtre par tenant (multi-tenancy)

    Returns:
        Migration si trouvee, None sinon
    """
    query = db.query(Migration).filter(Migration.id == migration_id)
    if tenant_id is not None:
        query = query.filter(Migration.tenant_id == tenant_id)
    return query.first()


def get_migrations(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        status: Optional[MigrationStatus] = None,
        strategy: Optional[MigrationStrategy] = None,
        vm_id: Optional[int] = None
) -> List[Migration]:
    """
    Recupere une liste de migrations avec filtres et pagination.

    Args:
        db: Session de base de donnees
        skip: Nombre d'elements a ignorer (pagination)
        limit: Nombre maximum d'elements a retourner
        tenant_id: Filtrer par tenant (multi-tenancy)
        status: Filtrer par statut de migration
        strategy: Filtrer par strategie de migration
        vm_id: Filtrer par VM

    Returns:
        Liste de migrations (ordonnee par created_at desc)
    """
    query = db.query(Migration)

    if tenant_id is not None:
        query = query.filter(Migration.tenant_id == tenant_id)

    if status is not None:
        query = query.filter(Migration.status == status)

    if strategy is not None:
        query = query.filter(Migration.strategy == strategy)

    if vm_id is not None:
        query = query.filter(Migration.vm_id == vm_id)

    return query.order_by(Migration.created_at.desc()).offset(skip).limit(limit).all()


def get_migrations_count(
        db: Session,
        tenant_id: Optional[str] = None,
        status: Optional[MigrationStatus] = None,
        strategy: Optional[MigrationStrategy] = None,
        vm_id: Optional[int] = None
) -> int:
    """
    Compte le nombre total de migrations avec les memes filtres.

    Args:
        db: Session de base de donnees
        tenant_id: Filtrer par tenant
        status: Filtrer par statut
        strategy: Filtrer par strategie
        vm_id: Filtrer par VM

    Returns:
        Nombre de migrations correspondantes
    """
    query = db.query(Migration)

    if tenant_id is not None:
        query = query.filter(Migration.tenant_id == tenant_id)

    if status is not None:
        query = query.filter(Migration.status == status)

    if strategy is not None:
        query = query.filter(Migration.strategy == strategy)

    if vm_id is not None:
        query = query.filter(Migration.vm_id == vm_id)

    return query.count()


def create_migration(
        db: Session,
        data: dict,
        tenant_id: str,
        target_namespace: str
) -> Migration:
    """
    Cree une nouvelle migration.

    Args:
        db: Session de base de donnees
        data: Champs de la migration (depuis schema.model_dump)
        tenant_id: Tenant proprietaire
        target_namespace: Namespace OpenShift cible (impose par le tenant)

    Returns:
        Migration creee
    """
    migration = Migration(
        **data,
        tenant_id=tenant_id,
        target_namespace=target_namespace,
        status=MigrationStatus.PENDING
    )

    db.add(migration)
    db.flush()  # obtient l'id pour le FK de l'événement initial

    # Audit J1 — première entrée du journal: création de la migration.
    # Allocation atomique du sequence_id via AuditEmitter (US3 Q2).
    AuditEmitter.emit_state_transition(
        db,
        migration=migration,
        from_status=None,
        to_status=MigrationStatus.PENDING,
        actor_type="system",
        message="Migration created",
        commit=False,
    )

    db.commit()
    db.refresh(migration)

    return migration


# Champs proteges — status par le worker Celery, target_namespace immuable
_MIGRATION_PROTECTED_FIELDS = {"status", "target_namespace"}


def update_migration(
        db: Session,
        migration_id: int,
        update_data: dict,
        tenant_id: Optional[str] = None
) -> Optional[Migration]:
    """
    Met a jour une migration existante.

    Les champs proteges (status, target_namespace) sont exclus
    automatiquement — status est gere par le worker Celery,
    target_namespace est immuable apres creation.

    Args:
        db: Session de base de donnees
        migration_id: ID de la migration a mettre a jour
        update_data: Champs a mettre a jour (exclude_unset=True)
        tenant_id: Si fourni, filtre par tenant

    Returns:
        Migration mise a jour si trouvee, None sinon
    """
    migration = get_migration(db, migration_id, tenant_id=tenant_id)
    if not migration:
        return None

    for field, value in update_data.items():
        if field not in _MIGRATION_PROTECTED_FIELDS:
            setattr(migration, field, value)

    db.commit()
    db.refresh(migration)

    return migration


def delete_migration(
        db: Session,
        migration_id: int,
        tenant_id: Optional[str] = None
) -> bool:
    """
    Supprime une migration.

    Args:
        db: Session de base de donnees
        migration_id: ID de la migration a supprimer
        tenant_id: Si fourni, filtre par tenant

    Returns:
        True si supprimee, False si non trouvee

    Raises:
        ValueError: Si la migration est en cours (is_active)
        MigrationHasAuditTrail: Si des événements d'audit la référencent
            (rétention append-only — la suppression est refusée proprement).
    """
    migration = get_migration(db, migration_id, tenant_id=tenant_id)
    if not migration:
        return False

    if migration.is_active:
        raise ValueError("Impossible de supprimer une migration en cours")

    db.delete(migration)
    try:
        db.commit()
    except IntegrityError as e:
        # La FK ``migration_events.migration_id`` est ``ON DELETE NO ACTION`` :
        # si le journal d'audit référence cette migration, le DELETE parent
        # est refusé par la base. C'est la garantie de rétention de l'audit,
        # pas une erreur serveur — on remonte une exception métier dédiée.
        db.rollback()
        raise MigrationHasAuditTrail(
            "Cette migration possède un journal d'audit conservé "
            "(migration_events, append-only) et ne peut pas être supprimée."
        ) from e

    return True


# ---------------------------------------------------------------------------
# Privileged worker setters — bypass _MIGRATION_PROTECTED_FIELDS.
# These functions are called from Celery tasks, never from the API layer.
# ---------------------------------------------------------------------------

def set_migration_status(
    db: Session,
    migration_id: int,
    status: MigrationStatus,
) -> Optional[Migration]:
    """Privileged status setter for the orchestrator worker.

    Audit J1 — écrit un MigrationEvent append-only à chaque transition
    effective (old_status != new_status). Récupère ``error_code`` /
    ``error_message`` déjà posés sur la ligne pour enrichir l'événement
    sans paramètres supplémentaires : la séquence conventionnelle
    ``fail_migration()`` puis ``set_migration_status(FAILED)`` enregistre
    automatiquement le code et le message d'erreur dans l'audit.
    """
    migration = db.query(Migration).filter(Migration.id == migration_id).first()
    if not migration:
        return None

    old_status = migration.status
    now = datetime.now(timezone.utc)
    migration.status = status

    if status == MigrationStatus.VALIDATING and not migration.started_at:
        migration.started_at = now
    if status in (
        MigrationStatus.COMPLETED,
        MigrationStatus.FAILED,
        MigrationStatus.CANCELLED,
        MigrationStatus.ROLLED_BACK,
    ):
        migration.completed_at = now
        migration.success = (status == MigrationStatus.COMPLETED)

    # Audit J1 — journal append-only. Saute les no-ops (re-livraison
    # Celery qui repose le même statut) pour ne pas polluer l'historique.
    if old_status != status:
        if status == MigrationStatus.FAILED:
            AuditEmitter.emit_classified_error(
                db,
                migration=migration,
                error_code=migration.error_code or "ERR_MIG_INTERNAL",
                message=migration.error_message or "Migration failed",
                actor_type="worker",
                commit=False,
            )
        else:
            payload = (
                {"error_code": migration.error_code}
                if migration.error_code
                else None
            )
            AuditEmitter.emit_state_transition(
                db,
                migration=migration,
                from_status=old_status,
                to_status=status,
                actor_type="worker",
                message=migration.error_message,
                payload=payload,
                commit=False,
            )

    db.commit()
    db.refresh(migration)
    return migration


def update_migration_progress(
    db: Session,
    migration_id: int,
    *,
    progress: float,
    current_step: Optional[str] = None,
    step_number: Optional[int] = None,
) -> Optional[Migration]:
    """Update the progress fields without touching status."""
    migration = db.query(Migration).filter(Migration.id == migration_id).first()
    if not migration:
        return None

    migration.progress_percentage = max(0.0, min(100.0, progress))
    if current_step is not None:
        migration.current_step = current_step
    if step_number is not None:
        migration.current_step_number = step_number

    db.commit()
    db.refresh(migration)
    return migration


def fail_migration(
    db: Session,
    migration_id: int,
    *,
    error_code: str,
    error_message: str,
) -> Optional[Migration]:
    """Stamp error fields. Caller should also call set_migration_status(FAILED)."""
    migration = db.query(Migration).filter(Migration.id == migration_id).first()
    if not migration:
        return None

    migration.error_code = error_code
    migration.error_message = error_message
    db.commit()
    db.refresh(migration)
    return migration
