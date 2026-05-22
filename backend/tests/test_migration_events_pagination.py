"""
US3 — delta polling via ``since_sequence_id`` (T016).

The audit endpoint paginates by ``sequence_id``, not by offset. A client
that polls the endpoint passes the previous response's
``next_since_sequence_id`` so it only fetches new events (Q4 adaptive
polling depends on this for efficiency).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import list_migration_events
from app.crud import migration as crud_migration
from app.models.base import Base
from app.models.migration import MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import VirtualMachine


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    # SQLite ne fait pas respecter les FK par défaut — l'activer met les
    # tests sur le même contrat d'intégrité référentielle que PostgreSQL
    # en prod (sinon un `Migration.vm_id` pointant sur une VM inexistante
    # passe silencieusement).
    @event.listens_for(engine, "connect")
    def _fk_pragma_on_connect(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_vm(db_session, vm_id: int = 1, tenant: str = "t1") -> VirtualMachine:
    """Crée une VM minimale pour satisfaire la FK ``migrations.vm_id``."""
    vm = VirtualMachine(
        id=vm_id,
        tenant_id=tenant,
        name=f"vm-{vm_id}",
        cpu_cores=1,
        memory_mb=512,
        disk_gb=10,
    )
    db_session.add(vm)
    db_session.commit()
    db_session.refresh(vm)
    return vm


def _superuser() -> User:
    return User(
        email="su@example.com",
        username="su",
        hashed_password="x",
        tenant_id="ops",
        is_superuser=True,
    )


def _seed_migration_with_events(db_session, n_extra_transitions: int = 3):
    vm = _seed_vm(db_session)
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": vm.id,
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )
    # create_migration writes the PENDING event; drive a few transitions.
    transitions = [
        MigrationStatus.VALIDATING,
        MigrationStatus.PREPARING,
        MigrationStatus.TRANSFERRING,
        MigrationStatus.CONFIGURING,
    ][:n_extra_transitions]
    for status in transitions:
        crud_migration.set_migration_status(db_session, mig.id, status)
    return mig


def test_first_call_returns_all_events_with_since_zero(db_session):
    mig = _seed_migration_with_events(db_session, n_extra_transitions=3)

    response = list_migration_events(
        mig.id, 200, 0, None, db_session, _superuser(),
    )

    # 1 initial PENDING + 3 transitions = 4
    assert len(response.items) == 4
    assert [e.sequence_id for e in response.items] == [1, 2, 3, 4]
    assert response.next_since_sequence_id == 4
    assert response.has_more is False


def test_second_call_with_cursor_returns_no_overlap(db_session):
    mig = _seed_migration_with_events(db_session, n_extra_transitions=3)

    first = list_migration_events(
        mig.id, 200, 0, None, db_session, _superuser(),
    )
    cursor = first.next_since_sequence_id

    second = list_migration_events(
        mig.id, 200, cursor, None, db_session, _superuser(),
    )
    assert second.items == []
    assert second.has_more is False
    # An empty delta returns ``None`` so the client can distinguish
    # "nothing new since the cursor" from "cursor parked at sequence N".
    assert second.next_since_sequence_id is None


def test_pagination_truncates_when_limit_smaller_than_page(db_session):
    mig = _seed_migration_with_events(db_session, n_extra_transitions=4)
    # 1 initial + 4 transitions = 5 events total.

    first = list_migration_events(
        mig.id, 2, 0, None, db_session, _superuser(),
    )
    assert len(first.items) == 2
    assert first.has_more is True
    assert first.next_since_sequence_id == 2

    second = list_migration_events(
        mig.id, 2, first.next_since_sequence_id, None,
        db_session, _superuser(),
    )
    assert len(second.items) == 2
    assert second.has_more is True
    assert second.next_since_sequence_id == 4

    third = list_migration_events(
        mig.id, 2, second.next_since_sequence_id, None,
        db_session, _superuser(),
    )
    assert len(third.items) == 1
    assert third.has_more is False
    assert third.next_since_sequence_id == 5


def test_sequence_ids_are_strictly_monotonic_per_migration(db_session):
    mig = _seed_migration_with_events(db_session, n_extra_transitions=4)

    response = list_migration_events(
        mig.id, 200, 0, None, db_session, _superuser(),
    )
    seqs = [e.sequence_id for e in response.items]
    assert seqs == sorted(seqs), "sequence_ids must be ordered ascending"
    assert len(set(seqs)) == len(seqs), "sequence_ids must be unique per migration"
    assert seqs[0] == 1, "sequence_id starts at 1"
