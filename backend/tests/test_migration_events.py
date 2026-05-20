"""
Tests pour le journal d'audit append-only des migrations (Audit J1).

Valide :
- `create_migration` écrit un événement initial PENDING.
- `set_migration_status` écrit un événement à chaque transition réelle.
- Repostage du même statut (re-livraison Celery) = no-op, pas de pollution.
- Transition vers FAILED enrichit la charge utile avec `error_code`.
- L'endpoint `GET /migrations/{id}/events` 404 pour un autre tenant.
- `cancel_migration` enregistre la raison comme message audit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import (
    cancel_migration,
    list_migration_events,
    start_migration,
)
from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
from app.models.user import User
from app.schemas.migration import MigrationCancel


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser() -> User:
    return User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="t1", is_superuser=True,
    )


def _tenant_user(tenant: str) -> User:
    return User(
        email=f"{tenant}@example.com", username=tenant, hashed_password="x",
        tenant_id=tenant, is_superuser=False,
    )


def _seed_migration(db, tenant: str = "t1") -> Migration:
    """Utility — bypass `create_migration` so the initial event is NOT written.

    Useful for tests that want to start from a clean slate and exercise
    `set_migration_status` in isolation.
    """
    mig = Migration(
        tenant_id=tenant, vm_id=1, status=MigrationStatus.PENDING,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{tenant}",
    )
    db.add(mig)
    db.commit()
    return mig


def test_create_migration_writes_initial_pending_event(db_session):
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": 1, "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert len(events) == 1
    initial = events[0]
    assert initial.event_type == MigrationEventType.STATUS_CHANGE
    assert initial.from_status is None
    assert initial.to_status == MigrationStatus.PENDING.value
    assert initial.tenant_id == "t1"
    assert initial.migration_id == mig.id


def test_set_migration_status_writes_event_on_transition(db_session):
    mig = _seed_migration(db_session)
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.VALIDATING)
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.PREPARING)

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert [e.to_status for e in events] == [
        MigrationStatus.VALIDATING.value,
        MigrationStatus.PREPARING.value,
    ]
    assert events[0].from_status == MigrationStatus.PENDING.value
    assert events[1].from_status == MigrationStatus.VALIDATING.value


def test_no_op_status_repost_does_not_pollute_audit_log(db_session):
    """A re-delivered Celery task that reposts the same status MUST NOT log."""
    mig = _seed_migration(db_session)
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.VALIDATING)
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.VALIDATING)

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert len(events) == 1
    assert events[0].to_status == MigrationStatus.VALIDATING.value


def test_failed_transition_records_error_code_in_payload(db_session):
    mig = _seed_migration(db_session)
    crud_migration.fail_migration(
        db_session, mig.id, error_code="ERR_DISK_FULL", error_message="No space",
    )
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.FAILED)

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    failure = events[-1]
    assert failure.event_type == MigrationEventType.ERROR
    assert failure.to_status == MigrationStatus.FAILED.value
    assert failure.message == "No space"
    assert failure.payload == {"error_code": "ERR_DISK_FULL"}


def test_start_endpoint_records_pending_to_validating_event(db_session, monkeypatch):
    mig = _seed_migration(db_session)
    fake_task = MagicMock()
    fake_task.delay.return_value.id = "task-123"
    monkeypatch.setattr("app.api.v1.migrations.run_migration", fake_task)

    start_migration(mig.id, db_session, _superuser())

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    transition = next(
        e for e in events if e.to_status == MigrationStatus.VALIDATING.value
    )
    assert transition.from_status == MigrationStatus.PENDING.value
    assert transition.event_type == MigrationEventType.STATUS_CHANGE


def test_cancel_endpoint_records_reason_as_audit_message(db_session, monkeypatch):
    from app.core.celery_app import celery_app

    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
        celery_task_id="task-to-revoke",
    )
    db_session.add(mig)
    db_session.commit()
    monkeypatch.setattr(celery_app, "control", MagicMock())

    cancel_migration(
        mig.id, MigrationCancel(reason="Operator aborted"), db_session, _superuser(),
    )

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    cancellation = events[-1]
    assert cancellation.to_status == MigrationStatus.CANCELLED.value
    assert cancellation.from_status == MigrationStatus.TRANSFERRING.value
    assert cancellation.message == "Operator aborted"


def test_events_endpoint_404s_for_a_different_tenant(db_session):
    """A tenant must not see another tenant's audit log."""
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": 1, "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="owner",
        target_namespace="shiftwise-owner",
    )

    with pytest.raises(HTTPException) as exc:
        list_migration_events(mig.id, 200, db_session, _tenant_user("attacker"))
    assert exc.value.status_code == 404


def test_events_endpoint_returns_history_in_chronological_order(db_session):
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": 1, "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.VALIDATING)
    crud_migration.set_migration_status(db_session, mig.id, MigrationStatus.PREPARING)

    response = list_migration_events(mig.id, 200, db_session, _superuser())

    statuses = [e.to_status for e in response.items]
    assert statuses == [
        MigrationStatus.PENDING.value,
        MigrationStatus.VALIDATING.value,
        MigrationStatus.PREPARING.value,
    ]
    assert response.total == 3
