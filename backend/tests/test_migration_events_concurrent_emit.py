"""
US3 — concurrent emit serializes the ``sequence_id`` allocation (T018).

Two workers writing to the same migration MUST NOT collide on
``(migration_id, sequence_id)``. The ``_next_sequence_id`` helper takes
a ``SELECT ... FOR UPDATE`` lock on the parent migration row before
computing ``COALESCE(MAX(sequence_id), 0) + 1`` (R5).

Locking semantics are PostgreSQL-only — SQLite's ``BEGIN IMMEDIATE`` is
not the same primitive. On SQLite this test SKIPs; on PostgreSQL it
spawns two threads racing to emit and asserts both rows landed with
distinct strictly-monotonic ``sequence_id`` values.
"""

from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import MigrationStrategy
from app.models.migration_event import MigrationEvent, MigrationEventType
from app.models.virtual_machine import VirtualMachine


@pytest.fixture
def engine():
    # ``TEST_DATABASE_URL`` is set by the ``backend-postgres`` CI job; on a
    # developer machine the default SQLite engine triggers
    # ``_skip_unless_postgres`` and the race test no-ops.
    url = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    engine = create_engine(url)
    if engine.dialect.name == "postgresql":
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    if engine.dialect.name == "postgresql":
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _skip_unless_postgres(engine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip(
            "FOR UPDATE row lock semantics require PostgreSQL; "
            "SQLite serializes writes by default and cannot exercise the race"
        )


def _seed_vm(session) -> int:
    """Insert a minimal VM so Migration.vm_id satisfies its FK.

    SQLite (dev default) does not enforce foreign keys, but the CI Postgres
    service container does — without a real VM row, create_migration raises
    ForeignKeyViolation on migrations_vm_id_fkey.
    """
    vm = VirtualMachine(
        tenant_id="t1", name="evt-test-vm",
        cpu_cores=1, memory_mb=512, disk_gb=10,
    )
    session.add(vm)
    session.commit()
    return vm.id


def test_concurrent_emit_produces_unique_sequence_ids(engine, db_session):
    _skip_unless_postgres(engine)

    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": _seed_vm(db_session),
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )
    SessionLocal = sessionmaker(bind=engine)

    errors: list[Exception] = []

    def emit_one() -> None:
        try:
            session = SessionLocal()
            crud_migration_event.record_event(
                session,
                migration_id=mig.id,
                tenant_id=mig.tenant_id,
                event_type=MigrationEventType.STAGE_EVENT,
                to_status=mig.status.value,
                message="concurrent emit",
                commit=True,
            )
            session.close()
        except Exception as exc:  # noqa: BLE001 — surface any race fail
            errors.append(exc)

    threads = [threading.Thread(target=emit_one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], (
        f"Concurrent emit raised {len(errors)} unexpected exceptions: "
        f"{[type(e).__name__ for e in errors]}"
    )

    rows = (
        db_session.query(MigrationEvent)
        .filter(MigrationEvent.migration_id == mig.id)
        .order_by(MigrationEvent.sequence_id.asc())
        .all()
    )
    sequence_ids = [row.sequence_id for row in rows]
    assert len(sequence_ids) == len(set(sequence_ids)), (
        f"Duplicate sequence_ids under concurrent emit: {sequence_ids}"
    )
    # 1 initial + 8 concurrent emits = 9.
    assert len(sequence_ids) == 1 + 8
    assert sequence_ids == sorted(sequence_ids)
    assert sequence_ids[0] == 1
    assert sequence_ids[-1] == 9


def test_sequential_emit_in_sqlite_is_monotonic(db_session):
    """Sanity check on the in-memory fixture without the concurrency test."""
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": _seed_vm(db_session),
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )

    for i in range(5):
        crud_migration_event.record_event(
            db_session,
            migration_id=mig.id,
            tenant_id=mig.tenant_id,
            event_type=MigrationEventType.STAGE_EVENT,
            to_status=mig.status.value,
            message=f"seq-{i}",
            commit=False,
        )
    db_session.commit()

    events = crud_migration_event.list_events_for_migration(
        db_session, mig.id,
    )
    seqs = [e.sequence_id for e in events]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))
