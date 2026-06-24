"""
Direct unit coverage for :class:`app.services.audit_log.AuditEmitter` (US3).

The emitter was previously exercised only transitively through
``crud_migration.set_migration_status`` and the migrator orchestrator,
which left three of its four core methods plus the two ``safe_emit_*``
variants effectively untested. This file pins each behaviour down with
its own test so a regression in any single method surfaces immediately:

* ``emit_state_transition`` writes the right event_type / from_status /
  to_status with the canonical ``actor_type`` default.
* ``emit_stage_event`` echoes the migration's current status and routes
  to the STAGE_EVENT enum value.
* ``emit_classified_error`` puts the ``error_code`` in ``payload`` so the
  cross-migration report query can filter on it.
* ``emit_heartbeat`` uses the HEARTBEAT enum and the ``"worker"``
  actor_type unconditionally.
* ``safe_emit_stage_event`` and ``safe_emit_heartbeat`` swallow
  ``SQLAlchemyError``, roll the session back, and return ``None`` so the
  orchestrator continues after a transient DB hiccup.
* ``record_event`` rejects out-of-band ``actor_type`` strings at write
  time so the audit log cannot land arbitrary labels.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.models.base import Base
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
from app.services.audit_log import AuditEmitter


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_migration(db, tenant: str = "t1") -> Migration:
    """Bypass ``create_migration`` to start from a clean audit slate."""
    mig = Migration(
        tenant_id=tenant,
        vm_id=1,
        status=MigrationStatus.PENDING,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{tenant}",
    )
    db.add(mig)
    db.commit()
    return mig


# --- emit_state_transition --------------------------------------------------


def test_emit_state_transition_writes_state_transition_row(db_session):
    mig = _seed_migration(db_session)

    AuditEmitter.emit_state_transition(
        db_session,
        migration=mig,
        from_status=MigrationStatus.PENDING,
        to_status=MigrationStatus.VALIDATING,
        commit=True,
    )

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == MigrationEventType.STATE_TRANSITION
    assert event.from_status == "pending"
    assert event.to_status == "validating"
    assert event.actor_type == "worker"
    assert event.actor_id is None


def test_emit_state_transition_with_user_actor_records_actor_id_and_type(db_session):
    mig = _seed_migration(db_session)

    AuditEmitter.emit_state_transition(
        db_session,
        migration=mig,
        from_status=MigrationStatus.PENDING,
        to_status=MigrationStatus.CANCELLED,
        actor_id=42,
        actor_type="user",
        message="cancelled by operator",
        commit=True,
    )

    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    [event] = events
    assert event.actor_id == 42
    assert event.actor_type == "user"
    assert event.message == "cancelled by operator"


def test_emit_state_transition_with_from_status_none(db_session):
    """Initial PENDING-write has ``from_status=None`` to mark the first event."""
    mig = _seed_migration(db_session)

    AuditEmitter.emit_state_transition(
        db_session,
        migration=mig,
        from_status=None,
        to_status=MigrationStatus.PENDING,
        commit=True,
    )

    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.from_status is None
    assert event.to_status == "pending"


# --- emit_stage_event -------------------------------------------------------


def test_emit_stage_event_echoes_current_migration_status(db_session):
    mig = _seed_migration(db_session)
    mig.status = MigrationStatus.TRANSFERRING
    db_session.commit()

    AuditEmitter.emit_stage_event(
        db_session,
        migration=mig,
        message="populator phase started (3 disk(s))",
        commit=True,
    )

    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.event_type == MigrationEventType.STAGE_EVENT
    assert event.from_status is None
    # The to_status mirrors the migration's current status so the
    # timeline shows what stage the event happened during.
    assert event.to_status == "transferring"
    assert event.message == "populator phase started (3 disk(s))"


# --- emit_classified_error --------------------------------------------------


def test_emit_classified_error_routes_error_code_into_payload(db_session):
    mig = _seed_migration(db_session)
    mig.status = MigrationStatus.PREPARING
    db_session.commit()

    AuditEmitter.emit_classified_error(
        db_session,
        migration=mig,
        error_code="ERR_MIG_K8S_TIMEOUT",
        message="populator wait exceeded 600s",
        commit=True,
    )

    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.event_type == MigrationEventType.CLASSIFIED_ERROR
    assert event.payload == {"error_code": "ERR_MIG_K8S_TIMEOUT"}
    assert event.to_status == "preparing"
    assert event.message == "populator wait exceeded 600s"


# --- emit_heartbeat ---------------------------------------------------------


def test_emit_heartbeat_writes_heartbeat_row_with_worker_actor(db_session):
    mig = _seed_migration(db_session)
    mig.status = MigrationStatus.TRANSFERRING
    db_session.commit()

    AuditEmitter.emit_heartbeat(
        db_session,
        migration=mig,
        message="waiting on populator disk 0",
        commit=True,
    )

    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.event_type == MigrationEventType.HEARTBEAT
    assert event.actor_type == "worker"
    assert event.actor_id is None
    assert event.to_status == "transferring"


# --- safe_emit_stage_event / safe_emit_heartbeat ----------------------------


def test_safe_emit_stage_event_swallows_dberror_and_returns_none(db_session):
    """A transient DB failure during a stage_event emit MUST NOT abort the
    migration. ``safe_emit_stage_event`` logs at WARNING and returns ``None``;
    the session is rolled back so subsequent CRUD calls inherit a clean
    transaction (Q1.C — heartbeat / stage_event are degraded-not-failed).
    """
    mig = _seed_migration(db_session)

    # Force record_event to raise an OperationalError mimicking a deadlock /
    # lock_timeout / connection drop. We patch the CRUD layer so the
    # emitter still calls into it.
    with patch(
        "app.services.audit_log.record_event",
        side_effect=OperationalError("simulated deadlock", None, Exception("boom")),
    ):
        result = AuditEmitter.safe_emit_stage_event(
            db_session,
            migration=mig,
            message="populator phase started",
        )

    assert result is None, "safe_emit_stage_event MUST return None on DB failure"
    # The session is rolled back; subsequent inserts must still work.
    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert events == [], "no row should have been committed"

    # And the session is healthy — a real emit afterwards succeeds.
    AuditEmitter.emit_stage_event(
        db_session, migration=mig, message="recovered emit", commit=True,
    )
    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.message == "recovered emit"


def test_safe_emit_heartbeat_swallows_dberror_and_returns_none(db_session):
    mig = _seed_migration(db_session)
    mig.status = MigrationStatus.TRANSFERRING
    db_session.commit()

    with patch(
        "app.services.audit_log.record_event",
        side_effect=OperationalError("simulated lock_timeout", None, Exception("boom")),
    ):
        result = AuditEmitter.safe_emit_heartbeat(
            db_session,
            migration=mig,
            message="waiting on populator disk 1",
        )

    assert result is None
    events = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert events == []


def test_safe_emit_stage_event_propagates_payload_to_record_event(db_session):
    """Happy path of the safe variant — the row is written and returned."""
    mig = _seed_migration(db_session)
    mig.status = MigrationStatus.PREPARING
    db_session.commit()

    result = AuditEmitter.safe_emit_stage_event(
        db_session,
        migration=mig,
        message="adapter job submitted",
        payload={"job_name": "fixup-mig-42-disk-0"},
    )

    assert result is not None
    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.event_type == MigrationEventType.STAGE_EVENT
    assert event.payload == {"job_name": "fixup-mig-42-disk-0"}


# --- record_event actor_type validation -------------------------------------


def test_record_event_rejects_non_canonical_actor_type(db_session):
    """Catches a future caller writing ``"sys"`` / ``"admin"`` / typo into
    the audit log. The model column is String(16) free-form; this CRUD
    guard is our only enforcement.
    """
    mig = _seed_migration(db_session)

    with pytest.raises(ValueError) as exc:
        crud_migration_event.record_event(
            db_session,
            migration_id=mig.id,
            tenant_id=mig.tenant_id,
            event_type=MigrationEventType.STATE_TRANSITION,
            to_status=MigrationStatus.PENDING.value,
            actor_type="sys",  # not in ("worker", "user", "system")
        )

    assert "invalid actor_type" in str(exc.value)


@pytest.mark.parametrize("actor_type", ["worker", "user", "system"])
def test_record_event_accepts_every_canonical_actor_type(db_session, actor_type):
    mig = _seed_migration(db_session)

    crud_migration_event.record_event(
        db_session,
        migration_id=mig.id,
        tenant_id=mig.tenant_id,
        event_type=MigrationEventType.STATE_TRANSITION,
        to_status=MigrationStatus.PENDING.value,
        actor_type=actor_type,
        commit=True,
    )

    [event] = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert event.actor_type == actor_type


# --- commit=False semantics -------------------------------------------------


def test_emit_with_commit_false_does_not_flush_to_a_fresh_session(db_session):
    """``commit=False`` must NOT auto-commit — the caller groups the audit
    write with its own status mutation in a single begin/commit block."""
    mig = _seed_migration(db_session)

    AuditEmitter.emit_state_transition(
        db_session,
        migration=mig,
        from_status=MigrationStatus.PENDING,
        to_status=MigrationStatus.VALIDATING,
        commit=False,
    )
    # In-session: the row is staged.
    in_session = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert len(in_session) == 1

    db_session.rollback()
    # After rollback: gone.
    after_rollback = crud_migration_event.list_events_for_migration(db_session, mig.id)
    assert after_rollback == []
