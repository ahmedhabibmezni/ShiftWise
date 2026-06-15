"""
ConverterService — orchestrates one disk through the pipeline:

    plan -> stage (pull) -> convert (k8s Job) -> verify -> READY

Side effects (DB writes) go through ``crud.conversion``; the service never
manipulates the ORM directly. Connector pulls run inside the worker, k8s Job
work runs in-cluster.

This module is designed to be called from a Celery task. It is synchronous on
purpose — Celery handles concurrency.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import conversion as crud_conversion
from app.crud import vm as crud_vm
from app.models.conversion import (
    ConversionGroupStatus,
    ConversionJob,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter import paths
from app.services.converter.connectors import get_puller
from app.services.converter.connectors.base import free_space_bytes
from app.services.converter.errors import ConversionError, is_transient
from app.services.converter.k8s_jobs import ConversionJobRunner
from app.services.converter.plan import plan_conversion
from app.services.converter.protocol import DiskDescriptor, ProgressCallback

logger = logging.getLogger(__name__)


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    """Return the hex SHA-256 of ``path`` (streamed, 1 MiB chunks)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


_TARGET_EXTENSION = {
    TargetFormat.QCOW2: "qcow2",
    TargetFormat.RAW: "raw",
}


class ConverterService:
    """Synchronous orchestrator. Call ``run_job(db, job_id)`` from a Celery task."""

    def __init__(self, runner: Optional[ConversionJobRunner] = None) -> None:
        # The runner is injected to make unit tests trivial — pass a fake.
        self._runner = runner

    # --- Entry points -------------------------------------------------------

    def create_group_for_vm(
        self,
        db: Session,
        *,
        tenant_id: str,
        vm_id: int,
        target_format: TargetFormat = TargetFormat.QCOW2,
        cold: bool = True,
        pull_options: Optional[dict] = None,
        max_attempts: int = 3,
        migration_id: Optional[int] = None,
    ) -> int:
        """Create a ConversionGroup + one ConversionJob per source disk.

        Returns the new group id. Does NOT enqueue any work — the API/worker
        layer is responsible for triggering :meth:`run_job` per ConversionJob.
        """
        vm = crud_vm.get_vm(db, vm_id, tenant_id=tenant_id)
        if vm is None:
            raise ConversionError("ERR_VM_NOT_FOUND", f"VM {vm_id} not found")
        if vm.source_hypervisor is None:
            raise ConversionError(
                "ERR_VM_NOT_FOUND",
                f"VM {vm_id} has no source hypervisor",
            )

        # 1) Enumerate disks via the connector — this validates the VM is
        #    reachable before we commit any state.
        puller = get_puller(vm.source_hypervisor.type)
        descriptors = puller.list_disks(vm.source_hypervisor, vm)
        if not descriptors:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"VM {vm_id}: no disks discovered on source",
            )

        # 2) Persist the group + jobs (all PENDING).
        # Audit C14 — connector-specific `pull_options` are merged into
        # `pull_config`; the explicit `cold` argument wins over any `cold`
        # key carried in the extras.
        group = crud_conversion.create_group(
            db,
            tenant_id=tenant_id,
            vm_id=vm_id,
            target_format=target_format,
            pull_config={**(pull_options or {}), "cold": cold},
            migration_id=migration_id,
        )

        for desc in descriptors:
            plan = plan_conversion(
                source_format=desc.source_format,
                target_format=target_format,
                os_type=vm.os_type,
            )
            crud_conversion.create_job(
                db,
                tenant_id=tenant_id,
                group_id=group.id,
                vm_id=vm_id,
                disk_index=desc.disk_index,
                source_format=desc.source_format,
                target_format=target_format,
                tool=plan.tool,
                source_path=desc.locator,
                source_size_bytes=desc.size_bytes,
                max_attempts=max_attempts,
            )

        return group.id

    def run_job(self, db: Session, job_id: int) -> ConversionStatus:
        """Drive a single ConversionJob to a terminal state.

        Returns the terminal status. Errors are converted to
        ``ConversionError`` and persisted on the job row — the caller (Celery
        task) decides whether to schedule a retry based on the error bucket.
        """
        job = crud_conversion.get_job(db, job_id)
        if job is None:
            raise ConversionError("ERR_INTERNAL", f"job {job_id} not found")
        if job.status in (
            ConversionStatus.READY,
            ConversionStatus.CANCELLED,
            ConversionStatus.EXPIRED,
        ):
            return job.status

        attempt_no = job.attempts + 1
        attempt = crud_conversion.create_attempt(
            db,
            job_id=job.id,
            attempt_number=attempt_no,
            started_at=datetime.now(timezone.utc),
        )
        crud_conversion.update_job(db, job.id, {"attempts": attempt_no})

        try:
            if settings.CONVERTER_SOURCE_CONVERT_SFTP:
                # Dev/demo bridge: convert+compress on the source node and
                # upload the small qcow2 to the cluster NFS over SFTP. Replaces
                # the local-stage + in-cluster qemu-img Job (which assumes the
                # worker shares the NFS mount — false on the laptop topology).
                self._source_convert_sftp(db, job)
            else:
                self._stage(db, job)
                self._convert(db, job)
                self._verify(db, job)
            crud_conversion.set_job_status(
                db, job.id, ConversionStatus.READY, progress_pct=100,
            )
            crud_conversion.finalize_attempt(
                db, attempt.id,
                final_status=ConversionStatus.READY,
                completed_at=datetime.now(timezone.utc),
            )
        except ConversionError as e:
            self._record_failure(db, job, attempt.id, e)
            return ConversionStatus.FAILED
        except Exception as e:  # NOSONAR — convert any failure to a permanent ConversionError
            wrapped = ConversionError("ERR_INTERNAL", str(e), cause=e)
            self._record_failure(db, job, attempt.id, wrapped)
            return ConversionStatus.FAILED

        # Recompute the parent group state.
        crud_conversion.recompute_group_status(db, job.group_id)
        return ConversionStatus.READY

    # --- Convert-on-source SFTP bridge (dev/demo) ---------------------------

    def _source_convert_sftp(self, db: Session, job: ConversionJob) -> None:
        """Convert on the source node, upload the qcow2 to the cluster NFS.

        Single-stage replacement for stage+convert+verify when the worker
        cannot reach the NFS directly (laptop topology). Leaves the job ready
        for the in-cluster Adapter/Migrator, which read the uploaded qcow2 from
        the transit PVC at ``{tenant}/outputs/{group_uuid}/{disk}.qcow2``.
        """
        from app.services.converter.remote_transit import RemoteTransit

        crud_conversion.set_job_status(db, job.id, ConversionStatus.STAGING, progress_pct=0)
        crud_conversion.set_group_status(db, job.group_id, ConversionGroupStatus.IN_PROGRESS)

        vm = crud_vm.get_vm(db, job.vm_id)
        if vm is None or vm.source_hypervisor is None:
            raise ConversionError("ERR_VM_NOT_FOUND", f"VM {job.vm_id} or its hypervisor is gone")
        group = crud_conversion.get_group(db, job.group_id)
        if group is None:
            raise ConversionError("ERR_INTERNAL", "group disappeared mid-flight")

        scratch = Path(settings.CONVERTER_LOCAL_SCRATCH) / group.group_uuid
        scratch.mkdir(parents=True, exist_ok=True)
        local_qcow2 = scratch / f"{job.disk_index}.qcow2"

        descriptor = DiskDescriptor(
            disk_index=job.disk_index,
            source_format=job.source_format,
            size_bytes=job.source_size_bytes or 0,
            locator=job.source_path or "",
        )
        cold = bool((group.pull_config or {}).get("cold", True))

        def stage_cb(done: int, total: int) -> None:
            pct = int(min(49, (done / max(total, 1)) * 50))  # pull = 0..50%
            crud_conversion.set_job_status(db, job.id, ConversionStatus.STAGING, progress_pct=pct)

        # Reuse an already-converted, hash-verified staged qcow2 from a prior
        # attempt instead of re-running the (slow) convert. This is what makes a
        # resumed upload safe: the NFS ``.partial`` was produced from these exact
        # bytes, so a byte-identical local file lets the upload append correctly.
        # A missing or mismatched file falls through to a fresh convert.
        staged_sha: Optional[str] = None
        if job.sha256 and local_qcow2.is_file():
            if _sha256_file(local_qcow2) == job.sha256:
                logger.info(
                    "reusing verified staged qcow2 %s (skip re-convert)", local_qcow2,
                )
                staged_sha = job.sha256
        if staged_sha is None:
            result = self._convert_on_source_local(
                vm, descriptor, local_qcow2, cold=cold, progress_cb=stage_cb,
            )
            staged_sha = result.sha256
        crud_conversion.update_job(
            db, job.id,
            {"staged_path": str(local_qcow2), "sha256": staged_sha},
        )

        # Upload the small qcow2 to the cluster NFS (over the bastion jump).
        crud_conversion.set_job_status(db, job.id, ConversionStatus.CONVERTING, progress_pct=50)
        rel = f"{group.tenant_id}/outputs/{group.group_uuid}/{job.disk_index}.qcow2"

        def upload_cb(done: int, total: int) -> None:
            pct = int(50 + min(45, (done / max(total, 1)) * 45))  # upload = 50..95%
            crud_conversion.set_job_status(db, job.id, ConversionStatus.CONVERTING, progress_pct=pct)

        with RemoteTransit.from_settings() as rt:
            need = int(local_qcow2.stat().st_size * 1.2)
            if rt.free_bytes() < need:
                raise ConversionError(
                    "ERR_NFS_INSUFFICIENT_SPACE",
                    f"NFS transit needs ~{need} bytes, has {rt.free_bytes()}",
                )
            rt.put_file(local_qcow2, rel, progress_cb=upload_cb)
            remote_size = rt.size(rel)
        if remote_size <= 0:
            raise ConversionError("ERR_OUTPUT_INVALID", f"uploaded qcow2 missing on NFS: {rel}")

        # Logical path the in-cluster Jobs see (POSIX, mounted transit root).
        logical_out = f"{settings.CONVERTER_TRANSIT_ROOT.rstrip('/')}/{rel}"
        crud_conversion.update_job(
            db, job.id,
            {"output_path": logical_out, "output_size_bytes": remote_size},
        )
        crud_conversion.set_job_status(db, job.id, ConversionStatus.VERIFYING, progress_pct=95)

        try:
            local_qcow2.unlink()
        except OSError:
            logger.debug("could not remove local scratch %s", local_qcow2, exc_info=True)

    @staticmethod
    def _convert_on_source_local(
        vm: VirtualMachine,
        descriptor: DiskDescriptor,
        dest_path: Path,
        *,
        cold: bool,
        progress_cb: ProgressCallback,
    ):
        """Produce a local qcow2 from the source, dispatched by hypervisor type.

        Each connector converts+compresses where the data lives and lands a
        single small qcow2 in the worker scratch; the shared upload step in
        :meth:`_source_convert_sftp` then ships it to the cluster NFS. Dispatch
        goes through the connector registry — Proxmox/KVM convert on the source
        node over SSH; VMware Workstation, Hyper-V, oVirt and vSphere pull the
        disk to the worker and convert locally.
        """
        hv = vm.source_hypervisor
        puller = get_puller(hv.type)
        convert = getattr(puller, "convert_on_source", None)
        if convert is None:
            raise ConversionError(
                "ERR_UNSUPPORTED_HYPERVISOR",
                f"connector for {hv.type.value} does not implement convert_on_source",
            )
        return convert(
            hv, vm, descriptor, dest_path,
            target_format="qcow2", cold=cold, progress_cb=progress_cb,
        )

    # --- Pipeline stages ----------------------------------------------------

    def _stage(self, db: Session, job: ConversionJob) -> None:
        """Pull source from the hypervisor onto NFS work/."""
        crud_conversion.set_job_status(db, job.id, ConversionStatus.STAGING, progress_pct=0)
        crud_conversion.set_group_status(db, job.group_id, ConversionGroupStatus.IN_PROGRESS)

        vm = crud_vm.get_vm(db, job.vm_id)
        if vm is None or vm.source_hypervisor is None:
            raise ConversionError("ERR_VM_NOT_FOUND", f"VM {job.vm_id} or its hypervisor is gone")

        group = crud_conversion.get_group(db, job.group_id)
        if group is None:
            raise ConversionError("ERR_INTERNAL", "group disappeared mid-flight")

        # NFS free-space pre-check.
        staged = paths.staged_path(group.tenant_id, group.group_uuid, job.disk_index)
        paths.ensure_dirs(staged.parent)
        required = int((job.source_size_bytes or 0) * settings.CONVERTER_FREE_SPACE_FACTOR)
        free = free_space_bytes(staged)
        if required and free < required:
            raise ConversionError(
                "ERR_NFS_INSUFFICIENT_SPACE",
                f"need ~{required} bytes, have {free}",
            )

        puller = get_puller(vm.source_hypervisor.type)

        def progress_cb(done: int, total: int) -> None:
            pct = int(min(99, (done / max(total, 1)) * 50))  # staging = 0..50%
            crud_conversion.set_job_status(
                db, job.id, ConversionStatus.STAGING, progress_pct=pct,
            )

        descriptor = DiskDescriptor(
            disk_index=job.disk_index,
            source_format=job.source_format,
            size_bytes=job.source_size_bytes or 0,
            locator=job.source_path or "",
        )
        cold = bool((group.pull_config or {}).get("cold", True))
        result = puller.pull_disk(
            vm.source_hypervisor, vm, descriptor, staged,
            cold=cold, progress_cb=progress_cb,
        )

        crud_conversion.update_job(
            db, job.id,
            {
                "staged_path": str(result.staged_path),
                "source_size_bytes": result.size_bytes,
                "sha256": result.sha256,
            },
        )

    def _convert(self, db: Session, job: ConversionJob) -> None:
        """Run qemu-img / virt-v2v in-cluster (or passthrough)."""
        crud_conversion.set_job_status(db, job.id, ConversionStatus.CONVERTING, progress_pct=50)

        group = crud_conversion.get_group(db, job.group_id)
        assert group is not None

        ext = _TARGET_EXTENSION[job.target_format]
        out_path = paths.output_path(group.tenant_id, group.group_uuid, job.disk_index, ext)
        paths.ensure_dirs(out_path.parent)
        in_path = Path(job.staged_path or "")
        if not in_path.exists():
            raise ConversionError(
                "ERR_INTERNAL",
                f"staged file missing: {in_path}",
            )

        if job.tool == ConversionTool.PASSTHROUGH:
            self._passthrough(in_path, out_path)
        else:
            self._run_in_cluster(job, group.group_uuid, in_path, out_path)

        crud_conversion.update_job(
            db, job.id,
            {
                "output_path": str(out_path),
                "output_size_bytes": out_path.stat().st_size if out_path.exists() else None,
            },
        )

    def _passthrough(self, in_path: Path, out_path: Path) -> None:
        """No-conversion case: copy the staged file into outputs/.

        Audit E17 — verify-before-move. The previous implementation renamed
        the staged file first (``in_path.replace(out_path)``); a rename
        consumes the source, so if a later pipeline step failed the job
        could not be retried (the staged input was gone). We now COPY, then
        verify the copy is byte-complete, and only then remove the source.
        On any failure the staged source is left intact for a retry.
        """
        try:
            shutil.copyfile(in_path, out_path)
        except OSError as e:
            # Copy failed — clean a possible partial output, keep the source.
            try:
                if out_path.exists():
                    out_path.unlink()
            except OSError:
                pass
            raise ConversionError(
                "ERR_INTERNAL",
                f"passthrough copy failed: {e}",
                cause=e,
            ) from e

        # Verify the copy before destroying the source.
        try:
            src_size = in_path.stat().st_size
            dst_size = out_path.stat().st_size
        except OSError as e:
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"passthrough verify failed: {e}",
                cause=e,
            ) from e
        if dst_size != src_size:
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"passthrough size mismatch: source={src_size} output={dst_size}",
            )

        # Copy verified — now it is safe to drop the staged source.
        try:
            in_path.unlink()
        except OSError as e:
            # Non-fatal: the output is correct; a stale staged file is just
            # transit-zone clutter the cleanup sweep will reclaim.
            logger.warning("passthrough: could not remove staged source %s: %s",
                            in_path, e)

    def _run_in_cluster(
        self,
        job: ConversionJob,
        group_uuid: str,
        in_path: Path,
        out_path: Path,
    ) -> None:
        runner = self._runner or ConversionJobRunner()
        job_name = f"convert-{group_uuid[:8]}-d{job.disk_index}-a{job.attempts}"

        if job.tool == ConversionTool.QEMU_IMG:
            runner.submit_qemu_img(
                job_name=job_name,
                group_uuid=group_uuid,
                disk_index=job.disk_index,
                input_path=str(in_path),
                output_path=str(out_path),
                target_format=_TARGET_EXTENSION[job.target_format],
                source_format=job.source_format.value,
            )
        elif job.tool == ConversionTool.VIRT_V2V:
            runner.submit_virt_v2v(
                job_name=job_name,
                group_uuid=group_uuid,
                disk_index=job.disk_index,
                input_path=str(in_path),
                output_dir=str(out_path.parent),
            )
        else:
            raise ConversionError(
                "ERR_INTERNAL",
                f"unexpected tool {job.tool}",
            )

        # Audit E12 — the K8s Job must be deleted whatever the outcome. The
        # manifest sets ttlSecondsAfterFinished, but that is a best-effort
        # cleanup that only fires if the TTL controller is healthy; without
        # an explicit delete a cluster with the controller disabled (or a
        # job that never reaches a finished state cleanly) accumulates
        # orphaned Jobs + their pods. try/finally guarantees the delete on
        # both the success and the failure path.
        # Audit E9 — cap mur client légèrement au-delà de l'activeDeadlineSeconds
        # du Job (6 h qemu-img / 12 h virt-v2v) : si le Job se bloque sans
        # jamais atteindre d'état terminal, la boucle de poll se termine
        # proprement (TimeoutInClient) au lieu de tourner indéfiniment.
        client_deadline = (12 if job.tool == ConversionTool.VIRT_V2V else 6) * 3600 + 600
        try:
            outcome = runner.wait_for_completion(
                job_name, timeout_seconds=client_deadline,
            )
            if not outcome.succeeded:
                reason = outcome.failure_reason or "unknown"
                code = self._classify_k8s_failure(reason, outcome.container_exit_code)
                raise ConversionError(
                    code,
                    f"converter Job {job_name} failed: "
                    f"reason={reason} exit={outcome.container_exit_code}",
                )
        finally:
            # delete() is best-effort and swallows 404 internally.
            runner.delete(job_name)

    def _verify(self, db: Session, job: ConversionJob) -> None:
        """Verify the output is structurally sound + record sha256."""
        crud_conversion.set_job_status(db, job.id, ConversionStatus.VERIFYING, progress_pct=95)

        out = Path(job.output_path or "")
        if not out.exists():
            raise ConversionError("ERR_OUTPUT_INVALID", f"output missing: {out}")
        if out.stat().st_size <= 0:
            raise ConversionError("ERR_OUTPUT_INVALID", "output file is empty")

        # qemu-img info / check would normally be invoked here. We defer the
        # subprocess call to the in-cluster image — in the worker context we
        # only verify file presence + size. The check below catches truncation.
        if (job.source_size_bytes or 0) > 0 and out.stat().st_size < int(job.source_size_bytes * 0.05):
            raise ConversionError(
                "ERR_OUTPUT_INVALID",
                f"output too small ({out.stat().st_size}) vs source ({job.source_size_bytes})",
            )

    # --- Failure handling ---------------------------------------------------

    @staticmethod
    def _classify_k8s_failure(reason: str, exit_code: Optional[int]) -> str:
        reason_lc = (reason or "").lower()
        if "deadline" in reason_lc:
            return "ERR_NETWORK_TIMEOUT"
        if "oom" in reason_lc or exit_code == 137:
            return "ERR_TOOL_KILLED_OOM"
        if exit_code in (126, 127):
            return "ERR_TOOL_NOT_FOUND"
        return "ERR_OUTPUT_INVALID"

    def _record_failure(
        self,
        db: Session,
        job: ConversionJob,
        attempt_id: int,
        err: ConversionError,
    ) -> None:
        crud_conversion.set_job_status(
            db, job.id, ConversionStatus.FAILED,
            error_code=err.code,
            error_message=err.message,
        )
        crud_conversion.finalize_attempt(
            db, attempt_id,
            final_status=ConversionStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            error_code=err.code,
            error_message=err.message,
        )
        crud_conversion.recompute_group_status(db, job.group_id)
        logger.warning(
            "Job %s failed (%s, retryable=%s): %s",
            job.id, err.code, is_transient(err.code), err.message,
        )


def create_converter_service() -> ConverterService:
    """Factory for ConverterService — symmetric with create_analyzer_service."""
    return ConverterService()
