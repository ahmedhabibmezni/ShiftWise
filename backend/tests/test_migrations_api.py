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

from app.api.v1.migrations import start_migration
from app.models.base import Base
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User


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
    monkeypatch.setattr("app.tasks.migration.run_migration", fake_task)

    start_migration(mig.id, db_session, _superuser())

    assert fake_task.delay.call_count == 1
    db_session.refresh(mig)
    assert mig.status != MigrationStatus.PENDING
