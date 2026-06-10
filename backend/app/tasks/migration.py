"""
Celery task — end-to-end orchestrator for one migration.

Pipeline (matches MigrationStatus state machine):
    PENDING -> VALIDATING -> PREPARING -> TRANSFERRING ->
    CONFIGURING -> STARTING -> VERIFYING -> COMPLETED

Each stage is wrapped so a failure transitions the row to FAILED with an
``error_code`` and ``error_message``. Conversion failures are surfaced from the
ConversionGroup status. Migrator failures are surfaced from MigratorError.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.celery_app import celery_app  # NOSONAR — import registers the app
from app.core.config import settings
from app.core.database import SessionLocal
from app.crud import conversion as crud_conversion
from app.crud import migration as crud_migration
from app.crud import vm as crud_vm
from app.models.conversion import ConversionGroupStatus, ConversionStatus
from app.models.migration import Migration, MigrationStatus
from app.services.adapter.errors import AdapterError
from app.services.adapter.service import AdapterService
from app.services.audit_log import AuditEmitter
from app.services.converter.errors import ConversionError
from app.services.converter.service import ConverterService
from app.services.migrator.errors import MigratorError
from app.services.migrator.service import MigratorService
from app.tasks.conversion import run_conversion_job

logger = logging.getLogger(__name__)


_FAILED_GROUP_STATES = {
    ConversionGroupStatus.FAILED,
    ConversionGroupStatus.PARTIAL,
    ConversionGroupStatus.CANCELLED,
}

# Audit E4 — terminal migration states. A re-delivered Celery task (broker
# at-least-once delivery, manual requeue) must NOT re-run the pipeline on a
# migration that already finished — that would duplicate ConversionGroups
# and re-create / overwrite KubeVirt resources.
_TERMINAL_MIGRATION_STATES = {
    MigrationStatus.COMPLETED,
    MigrationStatus.FAILED,
    MigrationStatus.CANCELLED,
    MigrationStatus.ROLLED_BACK,
}

# Audit E4 (hardening) — terminal states a failure write must NEVER overwrite.
# A re-delivered / duplicate orchestrator task that crashes must not flip a
# migration that already SUCCEEDED (or was deliberately cancelled / rolled
# back) to FAILED. FAILED is intentionally excluded: re-stamping a failure is
# harmless and may refresh the error message.
_PROTECTED_TERMINAL_STATES = {
    MigrationStatus.COMPLETED,
    MigrationStatus.CANCELLED,
    MigrationStatus.ROLLED_BACK,
}


@shared_task(
    name="app.tasks.migration.run_migration",
    bind=True,
    max_retries=0,  # the orchestrator is idempotent but not auto-retried
)
def run_migration(self, migration_id: int) -> str:
    """Drive Migration ``migration_id`` through its lifecycle. Returns status."""
    db = SessionLocal()
    try:
        migration = crud_migration.get_migration(db, migration_id)
        if migration is None:
            logger.error("Migration %s not found", migration_id)
            return MigrationStatus.FAILED.value

        # Audit E4 — terminal-state guard. If this task was re-delivered
        # (broker at-least-once semantics, an operator requeue, a duplicate
        # dispatch) after the migration already reached a terminal state,
        # short-circuit: re-running the pipeline would create duplicate
        # ConversionGroups and re-touch KubeVirt resources. Return the
        # existing terminal status unchanged.
        if migration.status in _TERMINAL_MIGRATION_STATES:
            logger.info(
                "Migration %s already terminal (%s) — skipping re-run",
                migration_id, migration.status.value,
            )
            return migration.status.value

        try:
            _validate(db, migration)
            _emit_stage(db, migration_id, "Validation passed — VM is eligible for migration")

            group_id = _prepare_conversions(db, migration)
            _emit_stage(
                db, migration_id,
                "Conversion jobs enqueued — transferring and converting source disks",
            )

            _wait_for_conversions(db, migration, group_id)
            _emit_stage(db, migration_id, "Disk conversion complete — all QCOW2 images ready")

            # The tenant namespace must exist BEFORE the Adapter submits its
            # Job into it. The Adapter runs ahead of the Migrator, which is the
            # canonical namespace creator (ensure_tenant_namespace, idempotent),
            # so without this the first migration into a brand-new tenant
            # namespace fails the Adapter Job create with a 404. Calling it here
            # and again in the Migrator is safe (idempotent).
            _ensure_tenant_namespace(migration)
            _emit_stage(
                db, migration_id,
                f"Tenant namespace {migration.target_namespace} ready",
            )

            # Adapter — guest OS fixup on each qcow2 in place.
            crud_migration.update_migration_progress(
                db, migration_id,
                progress=55.0,
                current_step="Adapting guest OS (network, console, GRUB)",
                step_number=4,
            )
            _emit_stage(
                db, migration_id,
                "Adapting guest OS — DHCP, serial console, GRUB redirect, SELinux relabel",
            )
            AdapterService().run(db, migration_id)
            _emit_stage(db, migration_id, "Guest OS adaptation complete")

            # Hand off to the Migrator: PVC populate + KubeVirt VM create + verify.
            crud_migration.update_migration_progress(
                db, migration_id,
                progress=65.0,
                current_step="Adapter done — handing off to migrator",
                step_number=5,
            )
            _set_status(db, migration_id, MigrationStatus.CONFIGURING)
            _emit_stage(
                db, migration_id,
                "Handing off to migrator — PVC populate and KubeVirt VM create",
            )
            terminal = MigratorService().run(db, migration_id)
            return terminal.value

        except SoftTimeLimitExceeded:
            _fail(db, migration_id, "ERR_TIMEOUT", "Soft time limit exceeded")
            raise
        except ConversionError as e:
            _fail(db, migration_id, e.code, e.message)
            return MigrationStatus.FAILED.value
        except AdapterError as e:
            _fail(db, migration_id, e.code, e.message)
            return MigrationStatus.FAILED.value
        except MigratorError as e:
            _fail(db, migration_id, e.code, e.message)
            return MigrationStatus.FAILED.value
        except Exception as e:  # NOSONAR — catch-all maps any crash to FAILED
            logger.exception("Migration %s crashed", migration_id)
            _fail(db, migration_id, "ERR_INTERNAL", str(e))
            return MigrationStatus.FAILED.value
    finally:
        db.close()


# --- stages ----------------------------------------------------------------

def _ensure_tenant_namespace(migration) -> None:
    """Create the tenant OpenShift namespace if absent (idempotent).

    Precondition for the Adapter stage, which submits a Job into
    ``migration.target_namespace``. Raises MigratorError (classified by HTTP
    status) on failure — caught by the orchestrator's MigratorError handler.
    """
    from app.core.kubevirt_client import get_kubevirt_client
    from app.services.migrator.namespace import ensure_tenant_namespace

    ensure_tenant_namespace(
        get_kubevirt_client(),
        migration.target_namespace,
        migration.tenant_id,
    )


def _validate(db, migration) -> None:
    _set_status(db, migration.id, MigrationStatus.VALIDATING)
    vm = crud_vm.get_vm(db, migration.vm_id)
    if vm is None:
        raise ConversionError("ERR_VM_NOT_FOUND", f"VM {migration.vm_id} disappeared")
    if not vm.can_migrate:
        raise ConversionError(
            "ERR_INTERNAL",
            f"VM {vm.id} is not eligible for migration (status={vm.status})",
        )


def _find_existing_group(db, migration):
    """Return a ConversionGroup already created for this migration, or None.

    Audit E4 — when ``run_migration`` is re-delivered on a still-running
    (non-terminal) migration, ``_prepare_conversions`` must NOT create a
    second ConversionGroup. We look up any group tied to this migration's
    VM + tenant and reuse the one whose ``migration_id`` matches.
    """
    candidates = crud_conversion.list_groups(
        db,
        tenant_id=migration.tenant_id,
        vm_id=migration.vm_id,
        limit=50,
    )
    for group in candidates:
        if getattr(group, "migration_id", None) == migration.id:
            return group
    return None


def _prepare_conversions(db, migration) -> int:
    """Create (or reuse) the ConversionGroup + jobs and enqueue each job."""
    _set_status(db, migration.id, MigrationStatus.PREPARING)

    # Audit E4 — reuse an existing group on a re-delivered task instead of
    # creating a duplicate.
    group = _find_existing_group(db, migration)
    if group is not None:
        logger.info(
            "Migration %s — reusing existing ConversionGroup %s (re-delivered task)",
            migration.id, group.id,
        )
        group_id = group.id
    else:
        service = ConverterService()
        group_id = service.create_group_for_vm(
            db,
            tenant_id=migration.tenant_id,
            vm_id=migration.vm_id,
            migration_id=migration.id,
        )
        group = crud_conversion.get_group(db, group_id)
        assert group is not None

    _set_status(db, migration.id, MigrationStatus.TRANSFERRING)
    for job in group.jobs:
        # run_conversion_job is itself idempotent (checks terminal status),
        # so re-enqueueing the jobs of a reused group is safe.
        run_conversion_job.delay(job.id)

    return group_id


def _wait_for_conversions(db, migration, group_id: int) -> None:
    """Block until the ConversionGroup leaves a non-terminal state.

    NOTE: this is a polling loop. With Celery chords/groups we could replace it
    with a callback, but polling is simpler and survives worker restarts (the
    state lives in PostgreSQL, not in Celery). The loop sleeps via
    ``self.retry`` is not used here because the orchestrator should remain a
    single task for traceability — instead we rely on ``run_conversion_job``
    finishing within the migration time limit.

    Audit E11 — the loop is bounded by an independent wall-clock deadline
    (``settings.MIGRATION_CONVERSION_WAIT_TIMEOUT``). A bare ``while True``
    would spin forever if a conversion Job silently stalled (e.g. a wedged
    K8s Job that never updates its group status), pinning the orchestrator
    until the Celery hard time limit. On deadline the loop raises
    ConversionError so the migration fails cleanly with a diagnosable code.
    """
    import time

    poll_interval = 5  # seconds
    deadline = time.monotonic() + max(0, settings.MIGRATION_CONVERSION_WAIT_TIMEOUT)
    while True:
        db.expire_all()
        group = crud_conversion.get_group(db, group_id)
        if group is None:
            raise ConversionError("ERR_INTERNAL", "conversion group vanished")

        if group.status == ConversionGroupStatus.READY:
            return
        if group.status in _FAILED_GROUP_STATES:
            raise ConversionError(
                "ERR_INTERNAL",
                f"conversion group ended in {group.status.value}",
            )

        # Audit E11 — independent wall-clock deadline. Checked AFTER the
        # terminal-state tests so a group that finished exactly at the
        # deadline is still reported as success/failure, not timeout.
        if time.monotonic() >= deadline:
            raise ConversionError(
                "ERR_NETWORK_TIMEOUT",
                f"conversion group {group_id} did not finish within "
                f"{settings.MIGRATION_CONVERSION_WAIT_TIMEOUT}s "
                f"(last status={getattr(group.status, 'value', group.status)})",
            )

        # Surface progress of the slowest job onto the migration row.
        jobs = group.jobs
        if jobs:
            avg = sum(j.progress_pct or 0 for j in jobs) / len(jobs)
            crud_migration.update_migration_progress(
                db, migration.id,
                progress=20.0 + (avg * 0.35),  # 20..55% during convert
                current_step=f"Converting {len(jobs)} disk(s) ({int(avg)}%)",
                step_number=3,
            )

        time.sleep(poll_interval)


# --- helpers ---------------------------------------------------------------

def _emit_stage(db, migration_id: int, message: str) -> None:
    """Best-effort human-readable stage_event for the audit timeline.

    Non-fatal (SAVEPOINT-isolated via ``safe_emit_stage_event``): a failed
    audit write degrades the timeline but never fails the migration. The
    caller's prior progress/status writes are already committed by their
    own CRUD helpers, so the safe emit's outer commit has nothing pending.
    """
    migration = crud_migration.get_migration(db, migration_id)
    if migration is not None:
        AuditEmitter.safe_emit_stage_event(db, migration=migration, message=message)


def _set_status(db, migration_id: int, status: MigrationStatus) -> None:
    crud_migration.set_migration_status(db, migration_id, status)


def _fail(db, migration_id: int, code: str, message: str) -> None:
    # Audit E4 (hardening) — re-read the row under a pessimistic lock right
    # before stamping the failure. A re-delivered or duplicate orchestrator
    # task (broker at-least-once delivery, a worker restart redelivering an
    # un-acked task) can crash on an already-finished migration; without this
    # guard its catch-all would overwrite a COMPLETED migration with FAILED.
    # The top-of-task terminal guard catches the common case, but this closes
    # the window where the row finished after the task started (or where the
    # worker is running stale code without that guard).
    locked = (
        db.query(Migration)
        .filter(Migration.id == migration_id)
        .with_for_update()
        .first()
    )
    if locked is not None and locked.status in _PROTECTED_TERMINAL_STATES:
        logger.warning(
            "Refusing to fail migration %s — already terminal (%s); "
            "ignoring spurious failure %s: %s",
            migration_id, locked.status.value, code, message,
        )
        db.commit()  # release the row lock
        return
    crud_migration.fail_migration(db, migration_id, error_code=code, error_message=message)
    crud_migration.set_migration_status(db, migration_id, MigrationStatus.FAILED)
    db.commit()
