"""
CRUD pour MigrationEvent — journal d'audit append-only.

Pas de mise à jour ni de suppression : ces événements sont écrits par
``crud_migration.set_migration_status`` et lus en consultation seule.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.migration_event import MigrationEvent, MigrationEventType


def list_events_for_migration(
    db: Session,
    migration_id: int,
    *,
    tenant_id: Optional[str] = None,
    limit: int = 200,
) -> List[MigrationEvent]:
    """Retourne les événements d'une migration, du plus ancien au plus récent.

    ``tenant_id`` filtre côté donnée — l'appelant API doit l'isolement
    multi-tenant. ``limit`` borne le volume retourné (audit complet → API
    paginée si besoin).
    """
    query = db.query(MigrationEvent).filter(
        MigrationEvent.migration_id == migration_id,
    )
    if tenant_id is not None:
        query = query.filter(MigrationEvent.tenant_id == tenant_id)
    return (
        query
        .order_by(MigrationEvent.created_at.asc(), MigrationEvent.id.asc())
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
    message: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> MigrationEvent:
    """Écrit un événement audit-log.

    Par défaut ``commit=True`` flushe la ligne immédiatement ; passez
    ``commit=False`` pour grouper l'écriture dans la même transaction que
    l'auteur (ex. ``set_migration_status``).
    """
    event = MigrationEvent(
        migration_id=migration_id,
        tenant_id=tenant_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
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
