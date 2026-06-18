"""
US3 — append-only enforcement (T014, T015).

The migration_events table is append-only at two layers:

1. Application layer — CRUD exposes only ``record_event`` and
   ``list_events_for_migration``; no UPDATE/DELETE path. Verified by the
   absence of mutation routes on the migrations router.
2. Database layer — a BEFORE UPDATE OR DELETE PL/pgSQL trigger raises
   ``migration_events is append-only`` unless the connection role is the
   migration runner (R4).

Layer 2 is PostgreSQL-specific. SQLite (the in-memory test fixture)
provides no PL/pgSQL, so these tests SKIP on sqlite. Run them with a
``DATABASE_URL`` pointing at a real PostgreSQL instance to validate.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, InternalError
from sqlalchemy.orm import sessionmaker

from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
from app.models.virtual_machine import VirtualMachine


# PostgreSQL function + trigger that the Alembic migration installs. Re-
# applied here so a CI run that bootstraps the schema with
# ``Base.metadata.create_all`` (no Alembic upgrade) still exercises the
# append-only contract end-to-end.
_PG_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION migration_events_no_mutation()
RETURNS trigger AS $$
BEGIN
    IF current_setting('shiftwise.migration_role', true)
            = 'migration_runner' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'migration_events is append-only';
END;
$$ LANGUAGE plpgsql;
"""

_PG_APPEND_ONLY_TRIGGER = """
DROP TRIGGER IF EXISTS trg_migration_events_no_mutation
ON migration_events;
CREATE TRIGGER trg_migration_events_no_mutation
BEFORE UPDATE OR DELETE ON migration_events
FOR EACH ROW
EXECUTE FUNCTION migration_events_no_mutation();
"""


@pytest.fixture
def db_session():
    # ``TEST_DATABASE_URL`` is set by the ``backend-postgres`` CI job to a
    # live Postgres service container. Defaulting to in-memory SQLite keeps
    # the test runnable on developer machines; the trigger assertions
    # auto-skip in that case via ``_skip_unless_postgres``.
    url = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    engine = create_engine(url)
    # Postgres CI: drop everything we own first so a previous run does not
    # contaminate the state. SQLite in-memory has no carry-over.
    if engine.dialect.name == "postgresql":
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(_PG_APPEND_ONLY_FUNCTION))
            conn.execute(text(_PG_APPEND_ONLY_TRIGGER))
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    if engine.dialect.name == "postgresql":
        Base.metadata.drop_all(engine)
    engine.dispose()


def _skip_unless_postgres(session) -> None:
    if session.bind.dialect.name != "postgresql":
        pytest.skip(
            "append-only trigger is PostgreSQL-only; run against a "
            "Postgres test database to exercise this guarantee"
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


def _seed_event(db_session):
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
    events = crud_migration_event.list_events_for_migration(
        db_session, mig.id,
    )
    assert events, "create_migration should have written the initial event"
    return events[0]


def test_db_trigger_blocks_update(db_session):
    _skip_unless_postgres(db_session)
    event = _seed_event(db_session)

    with pytest.raises((InternalError, DBAPIError)) as exc:
        db_session.execute(
            text(
                "UPDATE migration_events SET message = 'tampered' "
                "WHERE id = :id"
            ),
            {"id": event.id},
        )
        db_session.commit()
    assert "append-only" in str(exc.value)


def test_db_trigger_blocks_delete(db_session):
    _skip_unless_postgres(db_session)
    event = _seed_event(db_session)

    with pytest.raises((InternalError, DBAPIError)) as exc:
        db_session.execute(
            text("DELETE FROM migration_events WHERE id = :id"),
            {"id": event.id},
        )
        db_session.commit()
    assert "append-only" in str(exc.value)


def test_no_event_mutation_routes_exist():
    """The migrations router MUST NOT expose PUT/PATCH/DELETE on /events.

    Defense-in-depth: even if the DB trigger were dropped by mistake, the
    HTTP surface offers no way to issue a mutation.
    """
    from app.api.v1.migrations import router

    event_mutation_methods = []
    for route in router.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()))
        if path.endswith("/events") and methods & {"PUT", "PATCH", "DELETE"}:
            event_mutation_methods.append((path, methods))

    assert event_mutation_methods == [], (
        f"Found mutation methods on /events route: {event_mutation_methods}"
    )


def test_crud_module_has_no_update_or_delete_helpers():
    """The CRUD layer for migration_event MUST expose only insert/select.

    Catches a regression where a teammate adds ``update_event`` or
    ``delete_event`` without realising the table is append-only.
    """
    forbidden_names = {"update_event", "delete_event", "remove_event"}
    public_names = {
        name
        for name in dir(crud_migration_event)
        if not name.startswith("_")
    }
    leak = forbidden_names & public_names
    assert leak == set(), (
        f"crud/migration_event.py exposes forbidden mutation helpers: {leak}"
    )


def test_event_type_enum_has_exactly_four_canonical_values():
    """Catch accidental enum drift (Q1 set the canonical taxonomy)."""
    values = {member.value for member in MigrationEventType}
    assert values == {
        "state_transition",
        "stage_event",
        "classified_error",
        "heartbeat",
    }
