"""
CRUD pour MigrationEvent — journal d'audit append-only.

Pas de mise à jour ni de suppression : ces événements sont écrits par
``crud_migration.set_migration_status`` et lus en consultation seule. Le
endpoint ``GET /migrations/{id}/events`` ne supporte que la lecture
paginée par ``sequence_id``.

L'ordre canonique est ``sequence_id`` ascending par migration. Le
timestamp est conservé pour les requêtes de fenêtre temporelle mais ne
détermine PAS l'ordre des événements (rafale de heartbeats, dérive
d'horloge entre workers — Q2 production-readiness).
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.migration import Migration, MigrationStatus
from app.models.migration_event import MigrationEvent, MigrationEventType


def _next_sequence_id(db: Session, migration_id: int) -> int:
    """Allocate the next ``sequence_id`` for a migration.

    Locks the parent ``Migration`` row via ``SELECT ... FOR UPDATE`` so
    concurrent emitters cannot collide on ``(migration_id, sequence_id)``.
    Under PostgreSQL this is a real row lock; under SQLite (tests) the
    statement is a no-op and concurrency is precluded by the single
    writer thread.
    """
    db.query(Migration).filter(Migration.id == migration_id).with_for_update().first()
    current_max = (
        db.query(func.coalesce(func.max(MigrationEvent.sequence_id), 0))
        .filter(MigrationEvent.migration_id == migration_id)
        .scalar()
    )
    return int(current_max or 0) + 1


def list_events_for_migration(
    db: Session,
    migration_id: int,
    *,
    tenant_id: Optional[str] = None,
    since_sequence_id: int = 0,
    event_type: Optional[MigrationEventType] = None,
    limit: int = 200,
) -> List[MigrationEvent]:
    """Retourne les événements d'une migration, du plus ancien au plus récent.

    Ordre : ``sequence_id`` ascending (Q2). ``tenant_id`` filtre côté
    donnée — l'appelant API doit l'isolement multi-tenant.
    ``since_sequence_id`` autorise le polling delta : seuls les events
    avec ``sequence_id > since_sequence_id`` sont retournés.
    ``event_type`` filtre cross-migration (e.g.
    ``MigrationEventType.CLASSIFIED_ERROR`` pour les rapports d'incident).
    """
    query = db.query(MigrationEvent).filter(
        MigrationEvent.migration_id == migration_id,
    )
    if tenant_id is not None:
        query = query.filter(MigrationEvent.tenant_id == tenant_id)
    if since_sequence_id > 0:
        query = query.filter(MigrationEvent.sequence_id > since_sequence_id)
    if event_type is not None:
        query = query.filter(MigrationEvent.event_type == event_type)
    return (
        query
        .order_by(MigrationEvent.sequence_id.asc())
        .limit(limit)
        .all()
    )


def record_event(
    db: Session,
    *,
    migration_id: int,
    tenant_id: str,
    event_type: MigrationEventType,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_type: str = "worker",
    message: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> MigrationEvent:
    """Écrit un événement audit-log avec allocation atomique du ``sequence_id``.

    Par défaut ``commit=True`` flushe la ligne immédiatement ; passez
    ``commit=False`` pour grouper l'écriture dans la même transaction
    que l'auteur (ex. ``set_migration_status``). Le verrou ``FOR UPDATE``
    sur la migration parent garantit l'absence de collision sur
    ``(migration_id, sequence_id)`` même sous emit concurrent.
    """
    sequence_id = _next_sequence_id(db, migration_id)
    event = MigrationEvent(
        migration_id=migration_id,
        tenant_id=tenant_id,
        sequence_id=sequence_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        actor_type=actor_type,
        message=message,
        payload=payload,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def emit_heartbeat(
    db: Session,
    *,
    migration_id: int,
    tenant_id: str,
    current_status: MigrationStatus,
    message: Optional[str] = None,
    commit: bool = False,
) -> MigrationEvent:
    """Écrit un événement HEARTBEAT pour une étape longue (TRANSFERRING…).

    ``from_status`` est NULL (pas une transition), ``to_status`` répète
    le statut courant pour permettre au timeline UI d'afficher la durée
    écoulée dans la même étape. Le défaut ``commit=False`` reflète
    l'usage attendu : appel depuis la boucle du worker, qui commit en
    bloc à la fin de l'étape.
    """
    return record_event(
        db,
        migration_id=migration_id,
        tenant_id=tenant_id,
        event_type=MigrationEventType.HEARTBEAT,
        from_status=None,
        to_status=current_status.value,
        actor_type="worker",
        message=message,
        commit=commit,
    )
