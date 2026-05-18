"""
Tests for the Converter service.

Covers:
  - Plan decision matrix (qemu-img / virt-v2v / passthrough)
  - Error classification (transient / configurable / permanent)
  - Path layout safety (traversal rejected, tenant scoping)
  - CRUD: group + jobs + recompute_group_status PARTIAL detection
  - Service orchestration with fake puller + fake k8s runner
  - Cancel / retry flows on group state transitions
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.crud import conversion as crud_conversion
from app.models.base import Base
from app.models.conversion import (
    ConversionGroupStatus,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.user import User
from app.models.virtual_machine import OSType, VirtualMachine, VMStatus
from app.services.converter import paths
from app.services.converter.errors import ERROR_CATALOG, ConversionError, ErrorBucket
from app.services.converter.k8s_jobs import JobOutcome
from app.services.converter.plan import plan_conversion
from app.services.converter.protocol import DiskDescriptor, PullResult
from app.services.converter.service import ConverterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def tenant_id(db_session):
    u = User(
        email="t@x", username="t", hashed_password="x",
        tenant_id="tnt1", is_superuser=False,
    )
    db_session.add(u); db_session.commit()
    return u.tenant_id


@pytest.fixture
def hv(db_session, tenant_id):
    h = Hypervisor(
        name="kvm1", tenant_id=tenant_id, type=HypervisorType.KVM,
        host="kvm.local", username="r", password="x",
        status=HypervisorStatus.ACTIVE, total_vms_discovered=0,
    )
    db_session.add(h); db_session.commit()
    return h


@pytest.fixture
def vm_linux(db_session, tenant_id, hv):
    v = VirtualMachine(
        name="ubu1", tenant_id=tenant_id, source_hypervisor_id=hv.id,
        source_uuid="u1", cpu_cores=2, memory_mb=2048, disk_gb=20,
        os_type=OSType.LINUX, os_name="Ubuntu 22.04", os_version="22.04",
        status=VMStatus.DISCOVERED,
    )
    db_session.add(v); db_session.commit()
    return v


# ---------------------------------------------------------------------------
# Plan engine
# ---------------------------------------------------------------------------

class TestPlan:
    def test_linux_vmdk_to_qcow2_uses_qemu_img(self):
        p = plan_conversion(
            source_format=SourceFormat.VMDK,
            target_format=TargetFormat.QCOW2,
            os_type=OSType.LINUX,
        )
        assert p.tool == ConversionTool.QEMU_IMG
        assert not p.inject_virtio

    def test_qcow2_to_qcow2_is_passthrough(self):
        p = plan_conversion(
            source_format=SourceFormat.QCOW2,
            target_format=TargetFormat.QCOW2,
            os_type=OSType.LINUX,
        )
        assert p.tool == ConversionTool.PASSTHROUGH

    def test_windows_always_routes_to_virt_v2v(self):
        p = plan_conversion(
            source_format=SourceFormat.QCOW2,
            target_format=TargetFormat.QCOW2,
            os_type=OSType.WINDOWS,
        )
        assert p.tool == ConversionTool.VIRT_V2V
        assert p.inject_virtio


# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------

class TestErrors:
    def test_catalog_buckets_complete(self):
        for code, spec in ERROR_CATALOG.items():
            assert spec.code == code
            assert isinstance(spec.bucket, ErrorBucket)

    def test_unknown_code_falls_back_to_internal(self):
        e = ConversionError("ERR_DOES_NOT_EXIST", "boom")
        assert e.code == "ERR_INTERNAL"
        assert e.bucket == ErrorBucket.PERMANENT

    def test_transient_is_retryable(self):
        assert ConversionError("ERR_NFS_TIMEOUT", "x").is_retryable
        assert not ConversionError("ERR_SOURCE_CORRUPT", "x").is_retryable


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

class TestPaths:
    def test_traversal_rejected(self):
        with pytest.raises(ValueError):
            paths.tenant_root("../etc")

    def test_tenant_scoping(self):
        a = paths.outputs_dir("tnt1", "uuid-aaa")
        b = paths.outputs_dir("tnt2", "uuid-aaa")
        assert "tnt1" in str(a)
        assert "tnt2" in str(b)
        assert a != b

    def test_unsafe_extension_rejected(self):
        with pytest.raises(ValueError):
            paths.output_path("t", "u", 0, "../bad")


# ---------------------------------------------------------------------------
# CRUD + group state recompute
# ---------------------------------------------------------------------------

class TestGroupStatusRecompute:
    def _make_group_with_jobs(self, db, tenant_id, vm, statuses):
        group = crud_conversion.create_group(
            db, tenant_id=tenant_id, vm_id=vm.id, target_format=TargetFormat.QCOW2,
        )
        for i, st in enumerate(statuses):
            j = crud_conversion.create_job(
                db,
                tenant_id=tenant_id, group_id=group.id, vm_id=vm.id,
                disk_index=i, source_format=SourceFormat.VMDK,
                target_format=TargetFormat.QCOW2, tool=ConversionTool.QEMU_IMG,
                source_path=f"/src/{i}", source_size_bytes=1000,
            )
            crud_conversion.set_job_status(db, j.id, st)
        return group

    def test_all_ready_marks_group_ready(self, db_session, tenant_id, vm_linux):
        g = self._make_group_with_jobs(
            db_session, tenant_id, vm_linux,
            [ConversionStatus.READY, ConversionStatus.READY],
        )
        crud_conversion.recompute_group_status(db_session, g.id)
        db_session.refresh(g)
        assert g.status == ConversionGroupStatus.READY

    def test_mix_ready_failed_marks_partial(self, db_session, tenant_id, vm_linux):
        g = self._make_group_with_jobs(
            db_session, tenant_id, vm_linux,
            [ConversionStatus.READY, ConversionStatus.FAILED],
        )
        crud_conversion.recompute_group_status(db_session, g.id)
        db_session.refresh(g)
        assert g.status == ConversionGroupStatus.PARTIAL

    def test_all_failed_marks_failed(self, db_session, tenant_id, vm_linux):
        g = self._make_group_with_jobs(
            db_session, tenant_id, vm_linux,
            [ConversionStatus.FAILED, ConversionStatus.FAILED],
        )
        crud_conversion.recompute_group_status(db_session, g.id)
        db_session.refresh(g)
        assert g.status == ConversionGroupStatus.FAILED

    def test_in_flight_marks_in_progress(self, db_session, tenant_id, vm_linux):
        g = self._make_group_with_jobs(
            db_session, tenant_id, vm_linux,
            [ConversionStatus.READY, ConversionStatus.CONVERTING],
        )
        crud_conversion.recompute_group_status(db_session, g.id)
        db_session.refresh(g)
        assert g.status == ConversionGroupStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Service orchestration with fakes
# ---------------------------------------------------------------------------

class _FakePuller:
    """Pretends to enumerate + pull a single 1KB disk."""
    def __init__(self, raise_on_pull=None):
        self.raise_on_pull = raise_on_pull

    def list_disks(self, hv, vm):
        return [DiskDescriptor(
            disk_index=0,
            source_format=SourceFormat.VMDK,
            size_bytes=1024,
            locator="fake://disk0",
        )]

    def pull_disk(self, hv, vm, descriptor, dest_path, *, cold=True, progress_cb=None):
        if self.raise_on_pull is not None:
            raise self.raise_on_pull
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"x" * 1024)
        if progress_cb is not None:
            progress_cb(1024, 1024)
        return PullResult(
            staged_path=dest_path,
            source_format=descriptor.source_format,
            size_bytes=1024,
            sha256="deadbeef",
        )


class _FakeRunner:
    """Always succeeds; copies input -> output to mimic conversion."""
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.submitted = []

    def submit_qemu_img(self, *, job_name, group_uuid, disk_index,
                        input_path, output_path, target_format):
        self.submitted.append(("qemu", job_name, input_path, output_path))
        if self.succeed:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(Path(input_path).read_bytes())
        return job_name

    def submit_virt_v2v(self, **kw):
        self.submitted.append(("v2v", kw["job_name"]))
        return kw["job_name"]

    def wait_for_completion(self, job_name, **_):
        return JobOutcome(
            succeeded=self.succeed,
            failure_reason=None if self.succeed else "BackoffLimitExceeded",
            container_exit_code=0 if self.succeed else 1,
        )

    def delete(self, job_name, *, propagate=True):
        # Audit E12 — _run_in_cluster deletes the K8s Job in a finally block;
        # this mirrors the real ConversionJobRunner.delete() signature.
        self.submitted.append(("delete", job_name))


class TestServiceOrchestration:
    def test_create_group_and_run_job_to_ready(
        self, db_session, tenant_id, vm_linux, monkeypatch, tmp_path,
    ):
        # Redirect transit root onto tmp_path so tests don't touch /mnt.
        from app.services.converter import paths as converter_paths
        monkeypatch.setattr(
            converter_paths, "transit_root", lambda: tmp_path,
        )
        # Stub the registry to return our fake puller.
        from app.services.converter import service as svc_mod
        monkeypatch.setattr(svc_mod, "get_puller", lambda _t: _FakePuller())

        runner = _FakeRunner(succeed=True)
        svc = ConverterService(runner=runner)

        gid = svc.create_group_for_vm(
            db_session, tenant_id=tenant_id, vm_id=vm_linux.id,
        )
        group = crud_conversion.get_group(db_session, gid)
        assert group is not None
        assert len(group.jobs) == 1
        job = group.jobs[0]
        assert job.tool == ConversionTool.QEMU_IMG  # VMDK->QCOW2 / Linux

        terminal = svc.run_job(db_session, job.id)
        assert terminal == ConversionStatus.READY

        db_session.refresh(job)
        assert job.status == ConversionStatus.READY
        assert job.progress_pct == 100
        assert job.output_path is not None
        assert Path(job.output_path).exists()

        db_session.refresh(group)
        assert group.status == ConversionGroupStatus.READY

    def test_pull_failure_marks_job_failed(
        self, db_session, tenant_id, vm_linux, monkeypatch, tmp_path,
    ):
        from app.services.converter import paths as converter_paths
        monkeypatch.setattr(converter_paths, "transit_root", lambda: tmp_path)
        from app.services.converter import service as svc_mod
        boom = ConversionError("ERR_NFS_TIMEOUT", "simulated")
        monkeypatch.setattr(
            svc_mod, "get_puller", lambda _t: _FakePuller(raise_on_pull=boom),
        )

        svc = ConverterService(runner=_FakeRunner())
        gid = svc.create_group_for_vm(
            db_session, tenant_id=tenant_id, vm_id=vm_linux.id,
        )
        job = crud_conversion.get_group(db_session, gid).jobs[0]

        terminal = svc.run_job(db_session, job.id)
        assert terminal == ConversionStatus.FAILED

        db_session.refresh(job)
        assert job.error_code == "ERR_NFS_TIMEOUT"
        assert job.attempts == 1
        # Audit log should have one row with the same code.
        assert len(job.attempt_log) == 1
        assert job.attempt_log[0].error_code == "ERR_NFS_TIMEOUT"
