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

from app.core.celery_app import celery_app  # noqa: F401
from app.core.database import SessionLocal
from app.crud import conversion as crud_conversion
from app.crud import migration as crud_migration
from app.crud import vm as crud_vm
from app.models.conversion import ConversionGroupStatus, ConversionStatus
from app.models.migration import MigrationStatus
from app.services.adapter.errors import AdapterError
from app.services.adapter.service import AdapterService
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

        try:
            _validate(db, migration)
            group_id = _prepare_conversions(db, migration)
            _wait_for_conversions(db, migration, group_id)

            # Adapter — guest OS fixup on each qcow2 in place.
            crud_migration.update_migration_progress(
                db, migration_id,
                progress=55.0,
                current_step="Adapting guest OS (network, console, GRUB)",
                step_number=4,
            )
            AdapterService().run(db, migration_id)

            # Hand off to the Migrator: PVC populate + KubeVirt VM create + verify.
            crud_migration.update_migration_progress(
                db, migration_id,
                progress=65.0,
                current_step="Adapter done — handing off to migrator",
                step_number=5,
            )
            _set_status(db, migration_id, MigrationStatus.CONFIGURING)
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
        except Exception as e:  # noqa: BLE001
            logger.exception("Migration %s crashed", migration_id)
            _fail(db, migration_id, "ERR_INTERNAL", str(e))
            return MigrationStatus.FAILED.value
    finally:
        db.close()


# --- stages ----------------------------------------------------------------

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


def _prepare_conversions(db, migration) -> int:
    """Create the ConversionGroup + jobs and enqueue each job."""
    _set_status(db, migration.id, MigrationStatus.PREPARING)

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
    """
    import time

    poll_interval = 5  # seconds
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

def _set_status(db, migration_id: int, status: MigrationStatus) -> None:
    crud_migration.set_migration_status(db, migration_id, status)


def _fail(db, migration_id: int, code: str, message: str) -> None:
    crud_migration.fail_migration(db, migration_id, error_code=code, error_message=message)
    crud_migration.set_migration_status(db, migration_id, MigrationStatus.FAILED)
    db.commit()
