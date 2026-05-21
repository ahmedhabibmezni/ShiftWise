"""
US3 — indefinite retention independent of the parent migration (T019, Q3.A).

The ``migration_events`` FK on ``migration_id`` is ``ON DELETE NO ACTION``
(see Alembic revision a7c9b2e1f4d8). Deleting a migration row that has
audit history attached MUST raise a foreign-key violation — this is the
mechanism that guarantees FR-007's "lifetime is independent of the
parent migration row" promise.

SQLite enforces FKs only when the per-connection pragma
``foreign_keys=ON`` is set. The fixture enables it so the constraint
behaves like PostgreSQL for this test. Engines without enforced FK
support skip the test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import Migration, MigrationStrategy


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    # SQLite does not enforce FKs unless this PRAGMA is on per-connection.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_migration_with_event(db_session):
    mig = crud_migration.create_migration(
        db_session,
        data={
            "vm_id": 1,
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id="t1",
        target_namespace="shiftwise-t1",
    )
    events = crud_migration_event.list_events_for_migration(
        db_session, mig.id,
    )
    assert events, "create_migration writes an initial PENDING event"
    return mig


def test_deleting_migration_with_audit_history_raises_fk_violation(db_session):
    mig = _seed_migration_with_event(db_session)

    # delete_migration() blocks active migrations; PENDING is non-active
    # but we bypass it to exercise the FK constraint directly.
    db_session.delete(mig)
    with pytest.raises(IntegrityError) as exc:
        db_session.commit()
    db_session.rollback()

    assert "FOREIGN KEY" in str(exc.value).upper() or "constraint" in str(exc.value).lower()


def test_audit_rows_persist_when_delete_attempt_fails(db_session):
    mig = _seed_migration_with_event(db_session)
    mig_id = mig.id

    db_session.delete(mig)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Migration row still exists, and its events too.
    surviving = db_session.query(Migration).filter(Migration.id == mig_id).first()
    assert surviving is not None
    events = crud_migration_event.list_events_for_migration(
        db_session, mig_id,
    )
    assert events, "audit history must survive a failed delete"


def test_archival_path_requires_explicit_event_removal_first(db_session):
    """The documented archival path is: archive events out-of-band, THEN delete.

    This test does not perform the archival; it verifies that removing the
    audit rows directly (in the migration role, exempt from the trigger)
    unblocks the migration delete. In production this is the operator
    runbook step, not an application API.
    """
    mig = _seed_migration_with_event(db_session)
    mig_id = mig.id

    # Operator path — bypass the application CRUD via raw SQL. In
    # production this runs as the migration role; here SQLite has no
    # trigger so the DELETE just succeeds.
    db_session.execute(
        Migration.__table__.delete().where(Migration.id == -1)
    )  # no-op to confirm session is usable
    from sqlalchemy import text
    db_session.execute(
        text("DELETE FROM migration_events WHERE migration_id = :id"),
        {"id": mig_id},
    )
    db_session.commit()

    # Now the migration can be deleted.
    db_session.delete(mig)
    db_session.commit()

    surviving = db_session.query(Migration).filter(Migration.id == mig_id).first()
    assert surviving is None
