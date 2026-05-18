"""
Adapter orchestrator.

Drives the guest fixup phase between the Converter and the Migrator.

Pre-condition: each ConversionJob in the migration's READY group has an
``output_path`` pointing to a qcow2 on the transit volume.

Post-condition: each qcow2 has been mutated in place to:
  - drop a generic DHCP NIC config (matches all virtio NIC names)
  - enable serial-getty@ttyS0
  - patch GRUB to log on ttyS0
  - SELinux relabel

Idempotent. Safe to re-run on a partially adapted set of qcow2 files.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import conversion as crud_conversion
from app.crud import migration as crud_migration
from app.models.conversion import (
    ConversionGroupStatus,
    ConversionJob,
    ConversionStatus,
)
from app.services.adapter.errors import AdapterError
from app.services.adapter.guestfish_job import (
    AdapterOutcome,
    adapter_job_name,
    delete_adapter,
    get_adapter_logs,
    submit_adapter_job,
    wait_for_adapter,
)

logger = logging.getLogger(__name__)


class AdapterService:
    """Stateless orchestrator. One instance per worker is fine."""

    def run(self, db: Session, migration_id: int) -> None:
        """Adapt each qcow2 of the migration's READY conversion group.

        Returns when all disks have been adapted. Raises ``AdapterError``
        on the first failure — the orchestrator is fail-fast.
        """
        migration, group = self._load_context(db, migration_id)
        target_namespace = migration.target_namespace
        jobs = self._completed_jobs(group.jobs)
        if not jobs:
            raise AdapterError(
                "ERR_ADAPT_QCOW2_MISSING",
                f"No completed conversion jobs on group {group.id}",
            )

        for i, job in enumerate(jobs, start=1):
            self._adapt_one(
                migration_id=migration_id,
                tenant_id=migration.tenant_id,
                target_namespace=target_namespace,
                job=job,
                group_uuid=group.group_uuid,
            )
            crud_migration.update_migration_progress(
                db, migration_id,
                progress=55.0 + (10.0 * i / len(jobs)),
                current_step=f"Adapter: disk {job.disk_index} done ({i}/{len(jobs)})",
                step_number=4,
            )

    def cleanup(self, *, target_namespace: str, migration_id: int,
                disk_indices: list[int]) -> None:
        """Best-effort teardown — used by cancel / rollback flows."""
        for idx in disk_indices:
            try:
                delete_adapter(
                    namespace=target_namespace,
                    job_name=adapter_job_name(migration_id, idx),
                )
            except Exception as e:  # NOSONAR — best-effort cleanup, never raise
                logger.warning("cleanup: delete adapter %d failed: %s", idx, e)

    # --- internals -----------------------------------------------------

    def _load_context(self, db: Session, migration_id: int):
        migration = crud_migration.get_migration(db, migration_id)
        if migration is None:
            raise AdapterError(
                "ERR_ADAPT_INTERNAL", f"Migration {migration_id} not found",
            )
        if not migration.target_namespace:
            raise AdapterError(
                "ERR_ADAPT_INTERNAL",
                f"Migration {migration_id} has empty target_namespace",
            )

        groups = crud_conversion.list_groups(
            db,
            tenant_id=migration.tenant_id,
            vm_id=migration.vm_id,
            status=ConversionGroupStatus.READY,
            limit=1,
        )
        group = next(
            (g for g in groups if g.migration_id == migration_id),
            groups[0] if groups else None,
        )
        if group is None:
            raise AdapterError(
                "ERR_ADAPT_QCOW2_MISSING",
                f"No READY conversion group for migration {migration_id}",
            )
        return migration, group

    def _completed_jobs(self, jobs) -> list[ConversionJob]:
        ready = [
            j for j in jobs
            if j.status == ConversionStatus.READY and j.output_path
        ]
        ready.sort(key=lambda j: j.disk_index)
        return ready

    def _adapt_one(
        self,
        *,
        migration_id: int,
        tenant_id: str,
        target_namespace: str,
        job: ConversionJob,
        group_uuid: str,
    ) -> None:
        job_name = adapter_job_name(migration_id, job.disk_index)
        # Path on transit, relative to the NFS mount root.
        # Matches the converter's writeback layout: {tenant}/outputs/{group_uuid}/{idx}.qcow2
        rel = f"{tenant_id}/outputs/{group_uuid}/{job.disk_index}.qcow2"

        submit_adapter_job(
            namespace=target_namespace,
            job_name=job_name,
            migration_id=migration_id,
            disk_index=job.disk_index,
            src_relative_path=rel,
            active_deadline_seconds=settings.ADAPTER_TIMEOUT,
        )

        outcome = wait_for_adapter(
            namespace=target_namespace,
            job_name=job_name,
            timeout_seconds=settings.ADAPTER_TIMEOUT,
        )
        if not outcome.succeeded:
            self._raise_typed_failure(target_namespace, job_name, outcome,
                                      job.disk_index)

    def _raise_typed_failure(
        self,
        namespace: str,
        job_name: str,
        outcome: AdapterOutcome,
        disk_index: int,
    ) -> None:
        # Pull logs once for diagnosis. Stored in the exception message,
        # not the migration row (would bloat error_message — instead the
        # operator looks at the Job's pod logs via oc logs).
        logs_tail = get_adapter_logs(namespace=namespace, job_name=job_name)[-1500:]
        reason = outcome.failure_reason or "unknown"
        exit_code = outcome.container_exit_code

        if reason in ("DeadlineExceeded", "TimeoutInClient"):
            raise AdapterError(
                "ERR_ADAPT_K8S_TIMEOUT",
                f"Adapter for disk {disk_index} timed out ({reason}). "
                f"Tail:\n{logs_tail}",
            )
        if exit_code is not None and exit_code != 0:
            raise AdapterError(
                "ERR_ADAPT_VIRT_CUSTOMIZE_FAILED",
                f"Adapter disk {disk_index} exited {exit_code} "
                f"(reason: {reason}). Tail:\n{logs_tail}",
            )
        raise AdapterError(
            "ERR_ADAPT_INTERNAL",
            f"Adapter for disk {disk_index} failed: {reason}. Tail:\n{logs_tail}",
        )
