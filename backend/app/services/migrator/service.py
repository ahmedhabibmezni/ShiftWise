"""
Migrator orchestrator.

Drives a single Migration through the final three lifecycle states:

    CONFIGURING  -> populate target PVCs from converter outputs
    STARTING     -> create + start the KubeVirt VirtualMachine
    VERIFYING    -> wait for VMI to reach Running phase
    COMPLETED    -> stamp success on the Migration row

Idempotency:
    - PVC creation: 409 -> reuse
    - Populator Job submission: 409 -> reuse
    - VM creation: 409 -> caller must inspect (we treat that as
      ERR_MIG_VM_NAME_CONFLICT today; the orchestrator could re-attach but
      that's a future improvement)

Failure handling:
    - Any MigratorError raised inside the orchestrator is caught by the
      Celery task wrapper, which transitions the Migration row to FAILED
      and stamps error_code/error_message.
    - Best-effort cleanup of partially-created resources is NOT performed
      automatically (rollback is a separate explicit step). The
      ``cleanup`` method is provided for callers (cancel / rollback flows).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.kubevirt_client import (
    KubeVirtClientError,
    get_kubevirt_client,
    reauth_on_401,
)
from app.crud import conversion as crud_conversion
from app.crud import migration as crud_migration
from app.crud import vm as crud_vm
from app.models.conversion import ConversionGroupStatus, ConversionJob
from app.models.migration import Migration, MigrationStatus
from app.models.virtual_machine import VirtualMachine
from app.services.audit_log import AuditEmitter
from app.services.migrator.errors import MigratorError
from app.services.migrator.namespace import ensure_tenant_namespace
from app.services.migrator.populator_job import (
    PopulatorOutcome,
    delete_populator,
    get_populator_logs,
    populator_job_name,
    submit_populator_job,
    wait_for_populator,
)
from app.services.migrator.pvc import (
    compute_pvc_size_bytes,
    create_target_pvc,
    delete_pvc,
    target_pvc_name,
)
from app.services.migrator.vm_manifest import (
    DiskSpec,
    build_virtual_machine,
    sanitize_vm_name,
)

logger = logging.getLogger(__name__)


def _wait_vmi_running_with_reauth(
    *, namespace: str, name: str, timeout_seconds: int,
) -> dict:
    """``wait_vmi_running`` avec une relance unique sur 401/403 (Audit E20).

    En mode ``custom`` le jeton porteur KubeVirt peut expirer pendant le
    (long) poll de la VMI. Sur un échec d'authentification, ``reauth_on_401``
    invalide le client singleton mis en cache ; on relance alors une fois
    avec un client fraîchement reconstruit. Le poll est idempotent — un
    redémarrage est sans danger.

    Retourne la VMI à l'état Running (utilisée pour lire ``status.nodeName``).
    """
    try:
        return get_kubevirt_client().wait_vmi_running(
            name=name, namespace=namespace, timeout_seconds=timeout_seconds,
        )
    except KubeVirtClientError as exc:
        cause = exc.__cause__
        if isinstance(cause, ApiException) and reauth_on_401(cause):
            return get_kubevirt_client().wait_vmi_running(
                name=name, namespace=namespace, timeout_seconds=timeout_seconds,
            )
        raise


# Bytes per GiB — disk sizes are reported in binary gigabytes everywhere else
# in the migrator (compute_pvc_size_bytes), so the stamped GB metrics match.
_BYTES_PER_GIB = 1024 ** 3


class MigratorService:
    """Stateless orchestrator. One instance per worker is fine."""

    def run(self, db: Session, migration_id: int) -> MigrationStatus:
        """Drive a Migration to COMPLETED. Returns the terminal status.

        Pre-condition: the Converter has already finished and the
        ConversionGroup is READY. The caller (Celery task) is expected
        to have just transitioned the Migration to CONFIGURING.
        """
        migration, vm, group = self._load_context(db, migration_id)
        target_namespace = migration.target_namespace
        target_vm_name = self._resolve_target_vm_name(migration, vm)

        # Ensure the tenant namespace exists before anything else.
        # Creates shiftwise-{tenant_id} with standard labels if absent.
        # Feature 002 — resolve the client against the tenant's effective
        # cluster config (its own override → platform default → env bootstrap).
        kv = get_kubevirt_client(db, tenant_id=migration.tenant_id)
        ensure_tenant_namespace(kv, target_namespace, migration.tenant_id)

        # Cache the resolved VM name on the row so the UI sees it.
        if migration.target_vm_name != target_vm_name:
            migration.target_vm_name = target_vm_name
            db.commit()
            db.refresh(migration)

        jobs = self._completed_jobs(group.jobs)
        if not jobs:
            raise MigratorError(
                "ERR_MIG_QCOW2_MISSING",
                f"No completed conversion jobs on group {group.id}",
            )

        # ---- 1. Populate PVCs ------------------------------------------------
        self._update_progress(
            db, migration_id,
            progress=65.0,
            current_step=f"Populating {len(jobs)} target PVC(s)",
            step_number=5,
        )
        # US3 audit — stage_event marks the boundary so the timeline UI
        # shows the populate phase even when no state transition follows
        # within it.
        AuditEmitter.safe_emit_stage_event(
            db,
            migration=migration,
            message=f"populator phase started ({len(jobs)} disk(s))",
        )
        disks = self._populate_disks(
            db=db,
            migration_id=migration_id,
            tenant_id=migration.tenant_id,
            target_namespace=target_namespace,
            jobs=jobs,
            group_uuid=group.group_uuid,
        )

        # ---- 2. Create + start VM -------------------------------------------
        AuditEmitter.safe_emit_stage_event(
            db,
            migration=migration,
            message=f"populator phase finished ({len(disks)} disk(s) ready)",
        )
        self._set_status(db, migration_id, MigrationStatus.STARTING)
        self._update_progress(
            db, migration_id,
            progress=85.0,
            current_step=f"Creating VirtualMachine {target_vm_name}",
            step_number=6,
        )
        AuditEmitter.safe_emit_stage_event(
            db,
            migration=migration,
            message=f"creating VirtualMachine {target_vm_name}",
        )
        self._create_and_start_vm(
            namespace=target_namespace,
            name=target_vm_name,
            vm_row=vm,
            disks=disks,
            migration_id=migration_id,
        )

        # ---- 3. Wait for Running --------------------------------------------
        self._set_status(db, migration_id, MigrationStatus.VERIFYING)
        self._update_progress(
            db, migration_id,
            progress=95.0,
            current_step=f"Waiting for VMI {target_vm_name} to reach Running",
            step_number=7,
        )
        vmi = self._verify_running(namespace=target_namespace, name=target_vm_name)

        # ---- 4. Done ---------------------------------------------------------
        self._stamp_metrics(db, migration, jobs, vmi)
        self._stamp_success_on_vm_row(db, vm, target_namespace, target_vm_name)
        self._set_status(db, migration_id, MigrationStatus.COMPLETED)
        self._update_progress(
            db, migration_id,
            progress=100.0,
            current_step="Migration complete",
            step_number=7,
        )
        return MigrationStatus.COMPLETED

    # --- Best-effort cleanup ----------------------------------------------

    def cleanup(
        self,
        *,
        target_namespace: str,
        migration_id: int,
        disk_indices: list[int],
        target_vm_name: Optional[str],
    ) -> None:
        """Best-effort teardown — used by cancel / rollback flows.

        Swallows individual errors (logs them) so a partially populated
        migration can still be cleaned without an exception storm.
        """
        kv = get_kubevirt_client()

        if target_vm_name:
            try:
                kv.delete_vm(name=target_vm_name, namespace=target_namespace)
            except KubeVirtClientError as e:
                logger.warning("cleanup: delete VM failed: %s", e)

        for idx in disk_indices:
            try:
                delete_populator(
                    namespace=target_namespace,
                    job_name=populator_job_name(migration_id, idx),
                )
            except Exception as e:  # NOSONAR — best-effort cleanup, never raise
                logger.warning("cleanup: delete populator %d failed: %s", idx, e)
            try:
                delete_pvc(
                    namespace=target_namespace,
                    name=target_pvc_name(migration_id, idx),
                )
            except Exception as e:  # NOSONAR — best-effort cleanup, never raise
                logger.warning("cleanup: delete PVC %d failed: %s", idx, e)

    # ----------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------

    def _load_context(self, db: Session, migration_id: int):
        migration = crud_migration.get_migration(db, migration_id)
        if migration is None:
            raise MigratorError(
                "ERR_MIG_INTERNAL", f"Migration {migration_id} not found",
            )
        if not migration.target_namespace:
            raise MigratorError(
                "ERR_MIG_INTERNAL",
                f"Migration {migration_id} has empty target_namespace",
            )

        vm = crud_vm.get_vm(db, migration.vm_id)
        if vm is None:
            raise MigratorError(
                "ERR_MIG_INTERNAL", f"VM {migration.vm_id} disappeared",
            )

        groups = crud_conversion.list_groups(
            db,
            tenant_id=migration.tenant_id,
            vm_id=migration.vm_id,
            status=ConversionGroupStatus.READY,
            limit=1,
        )
        # Prefer the group attached to this migration if any.
        group = next(
            (g for g in groups if g.migration_id == migration_id),
            groups[0] if groups else None,
        )
        if group is None:
            raise MigratorError(
                "ERR_MIG_QCOW2_MISSING",
                f"No READY conversion group for VM {vm.id}",
            )
        return migration, vm, group

    def _resolve_target_vm_name(self, migration: Migration, vm: VirtualMachine) -> str:
        return sanitize_vm_name(
            migration.target_vm_name or vm.name,
            fallback=f"shiftwise-vm-{int(migration.id)}",
        )

    def _completed_jobs(self, jobs) -> list[ConversionJob]:
        from app.models.conversion import ConversionStatus
        ready = [
            j for j in jobs
            if j.status == ConversionStatus.READY and j.output_path
        ]
        ready.sort(key=lambda j: j.disk_index)
        return ready

    def _populate_disks(
        self,
        *,
        db: Session,
        migration_id: int,
        tenant_id: str,
        target_namespace: str,
        jobs: list[ConversionJob],
        group_uuid: str,
    ) -> list[DiskSpec]:
        disks: list[DiskSpec] = []

        for job in jobs:
            pvc_name = target_pvc_name(migration_id, job.disk_index)
            # The populator runs `qemu-img convert -O raw`, which writes the
            # disk's full *virtual* size — not the compressed/sparse on-disk
            # footprint of the qcow2 (output_size_bytes). source_size_bytes is
            # the source's provisioned capacity == the raw virtual size, so it
            # is the correct basis for the PVC. Take the max as a floor in case
            # one field is missing/zero for a given connector.
            virtual_size_bytes = max(
                job.source_size_bytes or 0,
                job.output_size_bytes or 0,
            )
            size_bytes = compute_pvc_size_bytes(virtual_size_bytes)
            create_target_pvc(
                namespace=target_namespace,
                name=pvc_name,
                size_bytes=size_bytes,
                storage_class=settings.MIGRATOR_TARGET_STORAGE_CLASS,
                labels={
                    "app.shiftwise.io/managed": "true",
                    "app.shiftwise.io/migration-id": str(migration_id),
                    "app.shiftwise.io/disk-index": str(job.disk_index),
                },
            )

            job_name = populator_job_name(migration_id, job.disk_index)
            src_rel = f"{tenant_id}/outputs/{group_uuid}/{job.disk_index}.qcow2"
            submit_populator_job(
                namespace=target_namespace,
                job_name=job_name,
                migration_id=migration_id,
                disk_index=job.disk_index,
                target_pvc_name=pvc_name,
                src_relative_path=src_rel,
                active_deadline_seconds=settings.MIGRATOR_POPULATOR_TIMEOUT,
            )

            # US3 audit — emit one heartbeat before the long wait so the
            # timeline shows liveness even before the next stage_event
            # lands. Proper periodic emission inside wait_for_populator()
            # is tracked as a TARGET (see specs/001-production-readiness).
            migration_row = crud_migration.get_migration(db, migration_id)
            if migration_row is not None:
                AuditEmitter.safe_emit_heartbeat(
                    db,
                    migration=migration_row,
                    message=f"waiting on populator disk {job.disk_index}",
                )

            outcome = wait_for_populator(
                namespace=target_namespace,
                job_name=job_name,
                timeout_seconds=settings.MIGRATOR_POPULATOR_TIMEOUT,
            )
            self._raise_if_populator_failed(
                outcome, job.disk_index,
                namespace=target_namespace, job_name=job_name,
            )

            disks.append(DiskSpec(
                disk_index=job.disk_index,
                pvc_name=pvc_name,
                is_boot=(job.disk_index == 0),
            ))

            self._update_progress(
                db, migration_id,
                progress=65.0 + (15.0 * (len(disks) / max(1, len(jobs)))),
                current_step=f"Populated disk {job.disk_index}",
                step_number=5,
            )

        return disks

    def _raise_if_populator_failed(
        self, outcome: PopulatorOutcome, disk_index: int,
        *, namespace: str | None = None, job_name: str | None = None,
    ) -> None:
        if outcome.succeeded:
            return
        # Map populator failures onto the migrator catalog.
        reason = outcome.failure_reason or "unknown"
        exit_code = outcome.container_exit_code
        if reason == "DeadlineExceeded" or reason == "TimeoutInClient":
            raise MigratorError(
                "ERR_MIG_K8S_TIMEOUT",
                f"Populator for disk {disk_index} timed out ({reason})",
            )
        if exit_code is not None and exit_code != 0:
            # qemu-img convert exit codes are not standardized. Inspect the pod
            # log to tell a too-small target PVC (ENOSPC mid-convert) apart from
            # a genuinely corrupt source — they demand different operator action.
            log_tail = ""
            if namespace and job_name:
                try:
                    log_tail = get_populator_logs(
                        namespace=namespace, job_name=job_name,
                    )
                except Exception:  # NOSONAR — diagnostics only, never mask the failure
                    log_tail = ""
            if "no space left on device" in log_tail.lower():
                raise MigratorError(
                    "ERR_MIG_PVC_TOO_SMALL",
                    f"Populator for disk {disk_index} ran out of space writing "
                    f"the raw image — target PVC is smaller than the disk's "
                    f"virtual size (exit {exit_code}).",
                )
            raise MigratorError(
                "ERR_MIG_QCOW2_CORRUPT",
                f"qemu-img convert disk {disk_index} exited {exit_code} "
                f"(reason: {reason})",
            )
        raise MigratorError(
            "ERR_MIG_INTERNAL",
            f"Populator for disk {disk_index} failed: {reason}",
        )

    def _create_and_start_vm(
        self,
        *,
        namespace: str,
        name: str,
        vm_row: VirtualMachine,
        disks: list[DiskSpec],
        migration_id: int,
    ) -> None:
        # Source boot firmware (captured at discovery into custom_metadata).
        # A UEFI guest must boot OVMF/EFI under KubeVirt; on the SeaBIOS default
        # it stalls at "Booting from Hard Disk..." with no legacy bootloader.
        firmware = (vm_row.custom_metadata or {}).get("firmware")
        manifest = build_virtual_machine(
            name=name,
            namespace=namespace,
            cpu_cores=vm_row.cpu_cores,
            memory_mb=vm_row.memory_mb,
            disks=disks,
            os_type=vm_row.os_type,
            mac_address=vm_row.mac_address,
            migration_id=migration_id,
            source_vm_id=vm_row.id,
            firmware=firmware,
        )
        kv = get_kubevirt_client()
        try:
            kv.create_vm_from_manifest(manifest)
        except KubeVirtClientError as e:
            # Conflict (409) usually means a VM with that name already exists.
            msg = str(e)
            if "already exists" in msg.lower() or "AlreadyExists" in msg:
                raise MigratorError(
                    "ERR_MIG_VM_NAME_CONFLICT",
                    f"A VM named {name!r} already exists in {namespace!r}",
                    cause=e,
                ) from e
            raise MigratorError(
                "ERR_MIG_VM_CREATE_REJECTED",
                f"KubeVirt rejected VM {namespace}/{name}: {msg}",
                cause=e,
            ) from e

        try:
            kv.set_vm_run_strategy(
                name=name, namespace=namespace, run_strategy="Always",
            )
        except KubeVirtClientError as e:
            raise MigratorError(
                "ERR_MIG_VM_CREATE_REJECTED",
                f"Could not start VM {namespace}/{name}: {e}",
                cause=e,
            ) from e

    def _verify_running(self, *, namespace: str, name: str) -> dict:
        try:
            return _wait_vmi_running_with_reauth(
                namespace=namespace,
                name=name,
                timeout_seconds=settings.MIGRATOR_VMI_RUNNING_TIMEOUT,
            )
        except KubeVirtClientError as e:
            raise MigratorError(
                "ERR_MIG_VMI_NEVER_RAN",
                f"VMI {namespace}/{name} did not reach Running: {e}",
                cause=e,
            ) from e

    def _stamp_metrics(
        self,
        db: Session,
        migration: Migration,
        jobs: list[ConversionJob],
        vmi: dict | None,
    ) -> None:
        """Record the result metrics (target node, sizes, throughput).

        Best-effort: a measurement gap must never fail an otherwise successful
        migration — these fields are display-only. ``source_size_bytes`` is the
        provisioned source capacity; ``output_size_bytes`` is the qcow2 actually
        produced and copied into the PVC (the data that crossed the wire).
        """
        try:
            source_bytes = sum(j.source_size_bytes or 0 for j in jobs)
            transferred_bytes = sum(j.output_size_bytes or 0 for j in jobs)
            if not transferred_bytes:
                transferred_bytes = source_bytes

            target_node = None
            if isinstance(vmi, dict):
                target_node = (vmi.get("status") or {}).get("nodeName")

            source_size_gb = (
                source_bytes / _BYTES_PER_GIB if source_bytes else None
            )
            transferred_gb = (
                transferred_bytes / _BYTES_PER_GIB if transferred_bytes else None
            )
            transfer_rate_mbps = self._effective_rate_mbps(
                migration, transferred_bytes,
            )

            crud_migration.set_migration_metrics(
                db,
                migration.id,
                target_node=target_node,
                source_size_gb=source_size_gb,
                transferred_gb=transferred_gb,
                transfer_rate_mbps=transfer_rate_mbps,
            )
        except Exception:  # NOSONAR — metrics are display-only, never fatal
            # A failed commit leaves the session in a failed-transaction state;
            # roll back so the subsequent success/status commits still run.
            db.rollback()
            logger.warning(
                "Failed to stamp result metrics on migration %s",
                migration.id, exc_info=True,
            )

    @staticmethod
    def _effective_rate_mbps(
        migration: Migration, transferred_bytes: int,
    ) -> float | None:
        """Throughput in Mbps over the elapsed migration time, or None.

        Uses ``started_at`` (stamped at VALIDATING) to now. Returns None when
        no data moved or the elapsed time is non-positive (clock skew / a
        re-delivered task), so a bogus rate never reaches the UI.
        """
        if not transferred_bytes or migration.started_at is None:
            return None
        started = migration.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_s = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed_s <= 0:
            return None
        return (transferred_bytes * 8) / elapsed_s / 1_000_000

    def _stamp_success_on_vm_row(
        self,
        db: Session,
        vm: VirtualMachine,
        namespace: str,
        vm_name: str,
    ) -> None:
        from app.models.virtual_machine import VMStatus
        vm.openshift_namespace = namespace
        vm.openshift_vm_name = vm_name
        vm.status = VMStatus.MIGRATED
        db.commit()
        db.refresh(vm)

    def _set_status(
        self, db: Session, migration_id: int, status: MigrationStatus,
    ) -> None:
        crud_migration.set_migration_status(db, migration_id, status)

    def _update_progress(
        self,
        db: Session,
        migration_id: int,
        *,
        progress: float,
        current_step: str,
        step_number: int,
    ) -> None:
        crud_migration.update_migration_progress(
            db, migration_id,
            progress=progress,
            current_step=current_step,
            step_number=step_number,
        )
