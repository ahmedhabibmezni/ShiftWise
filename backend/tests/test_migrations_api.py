"""
Tests pour les endpoints de l'API migrations.

Couvre H-18 : POST /migrations/{id}/start commit le statut VALIDATING avant
d'enfiler la tâche Celery. Si le broker est injoignable, .delay() lève et la
migration restait bloquée en VALIDATING sans tâche associée — donc
non-redémarrable. Le fix la remet en PENDING et renvoie 503.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import cancel_migration, create_migration, start_migration
from app.models.base import Base
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import (
    CompatibilityStatus,
    OSType,
    VirtualMachine,
    VMStatus,
)
from app.schemas.migration import MigrationCreate


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_pending_migration(db) -> Migration:
    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.PENDING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
    )
    db.add(mig)
    db.commit()
    return mig


def _superuser() -> User:
    return User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="t1", is_superuser=True,
    )


def test_start_reverts_to_pending_when_broker_unreachable(db_session, monkeypatch):
    mig = _seed_pending_migration(db_session)
    broker_down = MagicMock()
    broker_down.delay.side_effect = RuntimeError("broker unreachable")
    monkeypatch.setattr("app.tasks.migration.run_migration", broker_down)

    with pytest.raises(HTTPException) as exc:
        start_migration(mig.id, db_session, _superuser())

    # H-18: a broker outage must surface as 503, not strand the row.
    assert exc.value.status_code == 503
    db_session.refresh(mig)
    assert mig.status == MigrationStatus.PENDING


def test_start_enqueues_and_marks_started_when_broker_up(db_session, monkeypatch):
    mig = _seed_pending_migration(db_session)
    fake_task = MagicMock()
    fake_task.delay.return_value.id = "celery-task-xyz"
    monkeypatch.setattr("app.tasks.migration.run_migration", fake_task)

    start_migration(mig.id, db_session, _superuser())

    assert fake_task.delay.call_count == 1
    db_session.refresh(mig)
    assert mig.status != MigrationStatus.PENDING
    assert mig.celery_task_id == "celery-task-xyz"  # H-16


def test_start_rejects_non_pending_migration(db_session):
    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.COMPLETED,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
    )
    db_session.add(mig)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        start_migration(mig.id, db_session, _superuser())

    # H-20: the status is re-checked under a row lock before enqueue.
    assert exc.value.status_code == 400


def test_create_rejects_duplicate_active_migration(db_session):
    vm = VirtualMachine(
        name="vm1", tenant_id="t1", source_hypervisor_id=1, source_uuid="u1",
        cpu_cores=2, memory_mb=2048, disk_gb=10, os_type=OSType.LINUX,
        status=VMStatus.COMPATIBLE,
        compatibility_status=CompatibilityStatus.COMPATIBLE,
    )
    db_session.add(vm)
    db_session.commit()
    db_session.add(Migration(
        tenant_id="t1", vm_id=vm.id, status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
    ))
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        create_migration(MigrationCreate(vm_id=vm.id), db_session, _superuser())

    # H-19: a second active migration on the same VM is rejected (409).
    assert exc.value.status_code == 409


def test_cancel_revokes_the_celery_task(db_session, monkeypatch):
    from app.core.celery_app import celery_app

    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
        celery_task_id="task-to-revoke",
    )
    db_session.add(mig)
    db_session.commit()

    fake_control = MagicMock()
    monkeypatch.setattr(celery_app, "control", fake_control)

    cancel_migration(mig.id, None, db_session, _superuser())

    # H-16: cancelling must revoke the running task, not just flip the status.
    fake_control.revoke.assert_called_once()
    assert fake_control.revoke.call_args.args[0] == "task-to-revoke"
    assert fake_control.revoke.call_args.kwargs.get("terminate") is True
    db_session.refresh(mig)
    assert mig.status == MigrationStatus.CANCELLED
