"""
Audit-log emission service for the migration pipeline (US3).

Workers and request handlers MUST go through :class:`AuditEmitter` to write
audit rows; the inline ``db.add(MigrationEvent(...))`` pattern is forbidden
because it bypasses the ``sequence_id`` allocation lock (Q2) and the
actor/event-type discipline.

Every emit runs inside the same SQLAlchemy session and transaction as the
status mutation that caused it (R5). A failed audit emit rolls the status
update back too — an audit log that diverges from reality is worse than
no audit log at all.

The four emission helpers correspond to the canonical
:class:`MigrationEventType` categories:

- :meth:`emit_state_transition` for every transition between
  ``MigrationStatus`` enum values.
- :meth:`emit_stage_event` for pipeline-stage start/finish events
  (converter / adapter / migrator job lifecycle).
- :meth:`emit_classified_error` for K8s-boundary failures with a
  classified ``ERR_MIG_*`` code.
- :meth:`emit_heartbeat` for periodic (~30 s) liveness pings inside
  long-running stages.

The default ``commit=False`` semantics match the worker's per-stage
commit cadence: emit + status update happen in the same begin/commit
block.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.crud.migration_event import record_event
from app.models.migration import Migration, MigrationStatus
from app.models.migration_event import MigrationEvent, MigrationEventType


class AuditEmitter:
    """Single entry point for audit-log writes from the pipeline.

    All methods are static — there is no per-emitter state; the SQLAlchemy
    ``Session`` carries the transaction. Callers pass it explicitly so the
    caller's commit/rollback boundary is preserved.
    """

    @staticmethod
    def emit_state_transition(
        db: Session,
        *,
        migration: Migration,
        from_status: Optional[MigrationStatus],
        to_status: MigrationStatus,
        actor_id: Optional[int] = None,
        actor_type: str = "worker",
        message: Optional[str] = None,
        payload: Optional[dict] = None,
        commit: bool = False,
    ) -> MigrationEvent:
        """Record a ``MigrationStatus`` enum transition."""
        return record_event(
            db,
            migration_id=migration.id,
            tenant_id=migration.tenant_id,
            event_type=MigrationEventType.STATE_TRANSITION,
            from_status=from_status.value if from_status is not None else None,
            to_status=to_status.value,
            actor_id=actor_id,
            actor_type=actor_type,
            message=message,
            payload=payload,
            commit=commit,
        )

    @staticmethod
    def emit_stage_event(
        db: Session,
        *,
        migration: Migration,
        message: str,
        actor_id: Optional[int] = None,
        actor_type: str = "worker",
        payload: Optional[dict] = None,
        commit: bool = False,
    ) -> MigrationEvent:
        """Record a pipeline-stage lifecycle event.

        ``message`` is required and should describe the sub-step in human
        terms ("populator-job started", "adapter-job finished"). The
        ``to_status`` mirrors the migration's current status — operators
        reading the timeline see what stage the event happened during.
        """
        return record_event(
            db,
            migration_id=migration.id,
            tenant_id=migration.tenant_id,
            event_type=MigrationEventType.STAGE_EVENT,
            from_status=None,
            to_status=migration.status.value,
            actor_id=actor_id,
            actor_type=actor_type,
            message=message,
            payload=payload,
            commit=commit,
        )

    @staticmethod
    def emit_classified_error(
        db: Session,
        *,
        migration: Migration,
        error_code: str,
        message: str,
        actor_type: str = "worker",
        commit: bool = False,
    ) -> MigrationEvent:
        """Record a classified Kubernetes-boundary error.

        ``error_code`` SHOULD be one of the ``ERR_MIG_*`` codes already
        defined in the pipeline modules (e.g. ``ERR_MIG_K8S_TIMEOUT``,
        ``ERR_MIG_NAMESPACE_FORBIDDEN``). The code lands in the
        ``payload`` JSON column for cross-migration filtering.
        """
        return record_event(
            db,
            migration_id=migration.id,
            tenant_id=migration.tenant_id,
            event_type=MigrationEventType.CLASSIFIED_ERROR,
            from_status=None,
            to_status=migration.status.value,
            actor_id=None,
            actor_type=actor_type,
            message=message,
            payload={"error_code": error_code},
            commit=commit,
        )

    @staticmethod
    def emit_heartbeat(
        db: Session,
        *,
        migration: Migration,
        message: Optional[str] = None,
        commit: bool = False,
    ) -> MigrationEvent:
        """Record a liveness heartbeat for long-running stages.

        Emitted at most once per ~30 s from inside the migrator worker
        loop while the migration sits in TRANSFERRING or STARTING. The
        cadence is enforced by the caller (``time.monotonic`` deadline);
        this helper does not de-bounce.
        """
        return record_event(
            db,
            migration_id=migration.id,
            tenant_id=migration.tenant_id,
            event_type=MigrationEventType.HEARTBEAT,
            from_status=None,
            to_status=migration.status.value,
            actor_id=None,
            actor_type="worker",
            message=message,
            commit=commit,
        )
