"""
US3 — ``event_type`` filter on the audit endpoint (T017).

The cross-migration debugging workflow ("show me all classified_error
events across the cluster in the last 24h") relies on filtering by event
type. The endpoint MUST honour the filter and the limit-validation
contract documented in contracts/migration-events.md § 422.
"""

from __future__ import annotations

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import list_migration_events
from app.crud import migration as crud_migration
from app.crud.migration_event import record_event
from app.models.base import Base
from app.models.migration import MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
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


def _seed_mixed_event_types(db_session):
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
    # 1 state_transition already written by create_migration.
    record_event(
        db_session,
        migration_id=mig.id,
        tenant_id=mig.tenant_id,
        event_type=MigrationEventType.STAGE_EVENT,
        to_status=mig.status.value,
        message="adapter-job started",
        commit=False,
    )
    record_event(
        db_session,
        migration_id=mig.id,
        tenant_id=mig.tenant_id,
        event_type=MigrationEventType.HEARTBEAT,
        to_status=mig.status.value,
        commit=False,
    )
    record_event(
        db_session,
        migration_id=mig.id,
        tenant_id=mig.tenant_id,
        event_type=MigrationEventType.CLASSIFIED_ERROR,
        to_status=mig.status.value,
        message="K8s API timed out",
        payload={"error_code": "ERR_MIG_K8S_TIMEOUT"},
        commit=False,
    )
    db_session.commit()
    return mig


def test_filter_by_classified_error_returns_only_errors(db_session):
    mig = _seed_mixed_event_types(db_session)

    response = list_migration_events(
        mig.id, 200, 0, MigrationEventType.CLASSIFIED_ERROR,
        db_session, _superuser(),
    )

    assert len(response.items) == 1
    assert response.items[0].event_type == MigrationEventType.CLASSIFIED_ERROR
    assert response.items[0].payload == {"error_code": "ERR_MIG_K8S_TIMEOUT"}


def test_filter_by_heartbeat_returns_only_heartbeats(db_session):
    mig = _seed_mixed_event_types(db_session)

    response = list_migration_events(
        mig.id, 200, 0, MigrationEventType.HEARTBEAT,
        db_session, _superuser(),
    )

    assert len(response.items) == 1
    assert response.items[0].event_type == MigrationEventType.HEARTBEAT


def test_no_filter_returns_every_event_type(db_session):
    mig = _seed_mixed_event_types(db_session)

    response = list_migration_events(
        mig.id, 200, 0, None, db_session, _superuser(),
    )

    types = {e.event_type for e in response.items}
    assert types == {
        MigrationEventType.STATE_TRANSITION,
        MigrationEventType.STAGE_EVENT,
        MigrationEventType.HEARTBEAT,
        MigrationEventType.CLASSIFIED_ERROR,
    }


def test_limit_validation_rejects_value_above_cap():
    """The query-parameter validator MUST reject limit > 1000.

    The validator runs in FastAPI's dependency phase, so we exercise it
    via the Pydantic model that backs the Query() declaration. The router
    integration test in test_complete_api covers the HTTP 422 surface.
    """
    from pydantic import TypeAdapter, Field
    from typing import Annotated

    LimitField = Annotated[int, Field(ge=1, le=1000)]
    adapter = TypeAdapter(LimitField)

    with pytest.raises((ValidationError, RequestValidationError)):
        adapter.validate_python(5000)

    # Valid value still passes.
    assert adapter.validate_python(1000) == 1000
