"""
Celery task wiring — eager-mode tests.

We do NOT need a running Redis broker. ``celery_app.conf.task_always_eager``
runs tasks synchronously in the calling process. The tests verify:

- Task discovery (the celery app sees both tasks under their fully-qualified
  names).
- Routing config maps each task to the right queue.
- ``run_conversion_job`` writes ``celery_task_id`` and drives the job to
  ``READY`` when wired with fakes.

The deeper service-orchestration assertions live in test_converter.py — here
we just prove the Celery layer is correctly stitched onto it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.celery_app import celery_app
# Import task modules so the @shared_task decorators register on celery_app.
import app.tasks.conversion  # noqa: F401  # NOSONAR — side-effect import
import app.tasks.migration   # noqa: F401  # NOSONAR — side-effect import
from app.crud import conversion as crud_conversion
from app.models.base import Base
from app.models.conversion import ConversionStatus, SourceFormat
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.user import User
from app.models.virtual_machine import OSType, VirtualMachine, VMStatus

from app.services.converter.k8s_jobs import JobOutcome
from app.services.converter.protocol import DiskDescriptor, PullResult


class _FakePuller:
    def list_disks(self, hv, vm):
        return [DiskDescriptor(
            disk_index=0,
            source_format=SourceFormat.VMDK,
            size_bytes=1024,
            locator="fake://disk0",
        )]

    def pull_disk(self, hv, vm, descriptor, dest_path, *, cold=True, progress_cb=None):
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
    def submit_qemu_img(self, *, job_name, group_uuid, disk_index,
                        input_path, output_path, target_format):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(Path(input_path).read_bytes())
        return job_name

    def submit_virt_v2v(self, **kw):
        return kw["job_name"]

    def wait_for_completion(self, job_name, **_):
        return JobOutcome(succeeded=True, failure_reason=None, container_exit_code=0)

    def delete(self, job_name, *, propagate=True):
        # Audit E12 — _run_in_cluster deletes the K8s Job in a finally block.
        return None


@pytest.fixture(autouse=True)
def _eager_mode():
    """Force eager execution and propagate exceptions for assertions."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def seeded(db_session):
    u = User(
        email="t@x", username="t", hashed_password="x",
        tenant_id="tnt1", is_superuser=False,
    )
    db_session.add(u); db_session.commit()
    h = Hypervisor(
        name="kvm1", tenant_id=u.tenant_id, type=HypervisorType.KVM,
        host="kvm.local", username="r",
        status=HypervisorStatus.ACTIVE, total_vms_discovered=0,
    )
    db_session.add(h); db_session.commit()
    v = VirtualMachine(
        name="ubu1", tenant_id=u.tenant_id, source_hypervisor_id=h.id,
        source_uuid="u1", cpu_cores=2, memory_mb=2048, disk_gb=20,
        os_type=OSType.LINUX, os_name="Ubuntu 22.04", os_version="22.04",
        status=VMStatus.DISCOVERED,
    )
    db_session.add(v); db_session.commit()
    return {"tenant_id": u.tenant_id, "vm": v}


class TestTaskRegistry:
    def test_conversion_task_registered(self):
        assert "app.tasks.conversion.run_conversion_job" in celery_app.tasks

    def test_migration_task_registered(self):
        assert "app.tasks.migration.run_migration" in celery_app.tasks

    def test_routing_separates_queues(self):
        routes = celery_app.conf.task_routes
        assert routes["app.tasks.migration.*"]["queue"] == "migrations"
        assert routes["app.tasks.conversion.*"]["queue"] == "conversions"

    def test_durability_flags_set(self):
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True
        assert celery_app.conf.worker_prefetch_multiplier == 1


class TestConversionTaskEager:
    def test_run_conversion_job_drives_to_ready(
        self, db_session, seeded, monkeypatch, tmp_path,
    ):
        # Redirect transit root + stub puller registry.
        from app.services.converter import paths as converter_paths
        monkeypatch.setattr(converter_paths, "transit_root", lambda: tmp_path)
        from app.services.converter import service as svc_mod
        monkeypatch.setattr(svc_mod, "get_puller", lambda _t: _FakePuller())

        # Create the group + jobs via the service (one disk).
        from app.services.converter.service import ConverterService
        svc = ConverterService(runner=_FakeRunner())
        gid = svc.create_group_for_vm(
            db_session, tenant_id=seeded["tenant_id"], vm_id=seeded["vm"].id,
        )
        job = crud_conversion.get_group(db_session, gid).jobs[0]

        # Patch the task to use our session + runner. Wrap session so the
        # task's finally:db.close() doesn't kill the test fixture's session.
        from app.tasks import conversion as task_mod

        class _NonClosing:
            def __init__(self, real):
                self._real = real
            def __getattr__(self, name):
                if name == "close":
                    return lambda: None
                return getattr(self._real, name)

        monkeypatch.setattr(
            task_mod, "SessionLocal", lambda: _NonClosing(db_session),
        )
        monkeypatch.setattr(
            task_mod, "ConverterService",
            lambda: ConverterService(runner=_FakeRunner()),
        )

        # Run eagerly.
        job_id = job.id
        result = task_mod.run_conversion_job.apply(args=[job_id])
        assert result.successful()
        assert result.result == ConversionStatus.READY.value

        refreshed = crud_conversion.get_job(db_session, job_id)
        assert refreshed.status == ConversionStatus.READY
        assert refreshed.celery_task_id is not None
        assert Path(refreshed.output_path).exists()


class TestFailGuard:
    """Audit E4 hardening — _fail must not overwrite a successful terminal row."""

    def _make_migration(self, db, seeded, status):
        from app.models.migration import Migration, MigrationStatus, MigrationStrategy

        m = Migration(
            tenant_id=seeded["tenant_id"],
            vm_id=seeded["vm"].id,
            status=status,
            strategy=MigrationStrategy.AUTO,
            target_namespace="shiftwise-tnt1",
            success=(status == MigrationStatus.COMPLETED),
        )
        db.add(m)
        db.commit()
        return m

    def test_fail_refuses_to_overwrite_completed(self, db_session, seeded):
        from app.models.migration import MigrationStatus
        from app.tasks import migration as task_mod

        m = self._make_migration(db_session, seeded, MigrationStatus.COMPLETED)
        task_mod._fail(db_session, m.id, "ERR_INTERNAL", "stop")
        db_session.refresh(m)
        assert m.status == MigrationStatus.COMPLETED
        assert m.success is True
        assert m.error_message is None

    def test_fail_refuses_to_overwrite_cancelled(self, db_session, seeded):
        from app.models.migration import MigrationStatus
        from app.tasks import migration as task_mod

        m = self._make_migration(db_session, seeded, MigrationStatus.CANCELLED)
        task_mod._fail(db_session, m.id, "ERR_INTERNAL", "stop")
        db_session.refresh(m)
        assert m.status == MigrationStatus.CANCELLED

    def test_fail_marks_non_terminal_migration_failed(self, db_session, seeded):
        from app.models.migration import MigrationStatus
        from app.tasks import migration as task_mod

        m = self._make_migration(db_session, seeded, MigrationStatus.VALIDATING)
        task_mod._fail(db_session, m.id, "ERR_INTERNAL", "boom")
        db_session.refresh(m)
        assert m.status == MigrationStatus.FAILED
        assert m.success is False
        assert m.error_code == "ERR_INTERNAL"
        assert m.error_message == "boom"
