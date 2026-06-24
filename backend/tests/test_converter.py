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
        host="kvm.local", username="r",
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
# Transit cleanup (post-migration hygiene)
# ---------------------------------------------------------------------------

class TestCleanupTransitOutputs:
    def test_local_path_removes_outputs_dir(self, monkeypatch, tmp_path):
        from app.services.converter import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "CONVERTER_SOURCE_CONVERT_SFTP", False)
        monkeypatch.setattr(svc_mod.paths, "transit_root", lambda: tmp_path)
        out = svc_mod.paths.outputs_dir("tnt1", "grp-uuid")
        out.mkdir(parents=True)
        (out / "0.qcow2").write_bytes(b"x")
        assert out.exists()

        svc_mod.cleanup_transit_outputs("tnt1", "grp-uuid")
        assert not out.exists()

    def test_sftp_path_calls_remote_remove_dir(self, monkeypatch):
        from app.services.converter import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "CONVERTER_SOURCE_CONVERT_SFTP", True)

        calls = []

        class _FakeRT:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def remove_dir(self, rel_dir):
                calls.append(rel_dir)

        import app.services.converter.remote_transit as rt_mod

        monkeypatch.setattr(rt_mod.RemoteTransit, "from_settings", classmethod(lambda cls: _FakeRT()))

        svc_mod.cleanup_transit_outputs("tnt1", "grp-uuid")
        assert calls == ["tnt1/outputs/grp-uuid"]

    def test_missing_tenant_or_group_is_noop(self, monkeypatch):
        from app.services.converter import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "CONVERTER_SOURCE_CONVERT_SFTP", True)
        # Must not raise / must not attempt any remote work.
        svc_mod.cleanup_transit_outputs("", "grp-uuid")
        svc_mod.cleanup_transit_outputs("tnt1", "")

    def test_cleanup_swallows_errors(self, monkeypatch):
        """A cleanup failure must never propagate (would fail a done migration)."""
        from app.services.converter import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "CONVERTER_SOURCE_CONVERT_SFTP", True)

        import app.services.converter.remote_transit as rt_mod

        def _boom(cls):
            raise RuntimeError("transit unreachable")

        monkeypatch.setattr(rt_mod.RemoteTransit, "from_settings", classmethod(_boom))
        # Should log + swallow, not raise.
        svc_mod.cleanup_transit_outputs("tnt1", "grp-uuid")

    def test_remove_dir_refuses_empty_path(self):
        """Guard against an empty rel expanding to rm -rf on the export root."""
        import app.services.converter.remote_transit as rt_mod

        rt = rt_mod.RemoteTransit.__new__(rt_mod.RemoteTransit)  # bypass connect
        for bad in ("", "/", "///"):
            with pytest.raises(ConversionError):
                rt.remove_dir(bad)


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
                        input_path, output_path, target_format,
                        source_format=""):
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


# --- Proxmox disk-key enumeration (regression: scsihw treated as a disk) ------

class TestProxmoxDiskKeyMatching:
    """`scsihw: virtio-scsi-single` is a controller, not a disk.

    Regression for the converter spawning a bogus `disk_index 1` that failed
    every Proxmox migration with `ERR_DISK_NOT_FOUND` (pvesm path
    virtio-scsi-single → 'invalid format - unable to parse volume ID').
    """

    def test_real_disk_keys_match(self):
        from app.services.converter.connectors.proxmox import _is_disk_key
        assert _is_disk_key("scsi0")
        assert _is_disk_key("virtio0")
        assert _is_disk_key("sata1")
        assert _is_disk_key("ide0")
        assert _is_disk_key("scsi15")

    def test_controller_and_feature_keys_excluded(self):
        from app.services.converter.connectors.proxmox import _is_disk_key
        # The bug: `scsihw` starts with "scsi" but is the controller model.
        assert not _is_disk_key("scsihw")
        # `virtiofs0` starts with "virtio" but is a directory share, not a disk.
        assert not _is_disk_key("virtiofs0")
        # Unrelated config keys must never match.
        for k in ("name", "net0", "boot", "ostype", "smbios1", "memory", "cores"):
            assert not _is_disk_key(k)


# --- RemoteTransit path mapping + traversal guard (convert-on-source bridge) ---

class TestRemoteTransitPathMapping:
    """``_abs`` maps a POSIX-relative transit path onto the NFS export root and
    refuses traversal — it builds remote shell paths, so traversal would be a
    write-outside-export bug."""

    def _rt(self):
        from app.services.converter.remote_transit import RemoteTransit
        # No connection is opened; we only exercise pure path logic.
        return RemoteTransit(
            target_host="nfs.example", target_port=22, target_user="root",
            target_password="x", export_root="/nfs-storage/export",
        )

    def test_abs_joins_export_root(self):
        rt = self._rt()
        assert rt._abs("nextstep/outputs/abc/0.qcow2") == \
            "/nfs-storage/export/nextstep/outputs/abc/0.qcow2"
        # leading slash on the rel path is tolerated (treated as relative)
        assert rt._abs("/nextstep/x") == "/nfs-storage/export/nextstep/x"

    def test_abs_rejects_traversal(self):
        from app.services.converter.errors import ConversionError
        rt = self._rt()
        for bad in ("../etc/passwd", "nextstep/../../etc", "a/../../b"):
            with pytest.raises(ConversionError):
                rt._abs(bad)

    def test_requires_target_and_export(self):
        from app.services.converter.remote_transit import RemoteTransit
        from app.services.converter.errors import ConversionError
        with pytest.raises(ConversionError):
            RemoteTransit(target_host="", target_port=22, target_user="root",
                          target_password="x", export_root="/x")
        with pytest.raises(ConversionError):
            RemoteTransit(target_host="h", target_port=22, target_user="root",
                          target_password="x", export_root="")


# ---------------------------------------------------------------------------
# VMware Workstation connector
# ---------------------------------------------------------------------------

class _StubVM:
    """Minimal VirtualMachine-shaped stub for connector unit tests."""
    def __init__(self, name, custom_metadata):
        self.name = name
        self.custom_metadata = custom_metadata
        self.source_uuid = "u1"


def _write_vmx(tmp_path, body: str) -> str:
    vmx = tmp_path / "Proxmox" / "Proxmox.vmx"
    vmx.parent.mkdir(parents=True, exist_ok=True)
    vmx.write_text(body, encoding="utf-8")
    return str(vmx)


class TestVmwareWorkstationConnector:
    def test_extract_disk_files_filters_cdrom_and_controllers(self, tmp_path):
        from app.services.converter.connectors.vmware_workstation import (
            _extract_disk_files,
            _parse_vmx_file,
        )
        # Create the backing vmdk so absolute resolution is sane.
        (tmp_path / "Proxmox").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Proxmox" / "Proxmox.vmdk").write_bytes(b"x" * 1024)
        vmx = _write_vmx(
            tmp_path,
            'displayName = "Proxmox"\n'
            'scsi0.present = "TRUE"\n'
            'scsi0.virtualDev = "lsilogic"\n'           # controller, not a disk
            'scsi0:0.present = "TRUE"\n'
            'scsi0:0.fileName = "Proxmox.vmdk"\n'
            'scsi0:0.deviceType = "scsi-hardDisk"\n'
            'sata0:1.present = "TRUE"\n'
            'sata0:1.fileName = "linux.iso"\n'          # not a vmdk -> skip
            'sata0:1.deviceType = "cdrom-image"\n'
            'ide1:0.present = "TRUE"\n'
            'ide1:0.fileName = "ubuntu.iso"\n'
            'ide1:0.deviceType = "cdrom-image"\n',
        )
        config = _parse_vmx_file(vmx)
        disks = _extract_disk_files(vmx, config)
        assert len(disks) == 1
        device, path = disks[0]
        assert device == "scsi0:0"
        assert path.endswith("Proxmox.vmdk")

    def test_list_disks_returns_vmdk_descriptor(self, tmp_path):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors.vmware_workstation import (
            VmwareWorkstationPuller,
        )
        (tmp_path / "Proxmox").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Proxmox" / "Proxmox.vmdk").write_bytes(b"x" * (4 * 1024))
        vmx = _write_vmx(
            tmp_path,
            'scsi0:0.fileName = "Proxmox.vmdk"\n'
            'scsi0:0.deviceType = "scsi-hardDisk"\n',
        )
        vm = _StubVM("Proxmox", {"vmx_path": vmx})
        descriptors = VmwareWorkstationPuller().list_disks(None, vm)
        assert len(descriptors) == 1
        d = descriptors[0]
        assert d.disk_index == 0
        assert d.source_format == SourceFormat.VMDK
        assert d.size_bytes == 4 * 1024
        assert d.locator.endswith("Proxmox.vmdk")

    def test_list_disks_without_vmx_path_raises(self):
        from app.services.converter.connectors.vmware_workstation import (
            VmwareWorkstationPuller,
        )
        vm = _StubVM("Proxmox", {})
        with pytest.raises(ConversionError) as ei:
            VmwareWorkstationPuller().list_disks(None, vm)
        assert ei.value.code == "ERR_DISK_NOT_FOUND"

    def test_convert_on_source_produces_qcow2(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import vmware_workstation as ws
        from app.services.converter.connectors.vmware_workstation import (
            VmwareWorkstationPuller,
        )
        (tmp_path / "Proxmox").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Proxmox" / "Proxmox.vmdk").write_bytes(b"x" * (8 * 1024))
        vmx = _write_vmx(
            tmp_path,
            'scsi0:0.fileName = "Proxmox.vmdk"\n'
            'scsi0:0.deviceType = "scsi-hardDisk"\n',
        )
        vm = _StubVM("Proxmox", {"vmx_path": vmx})

        # VM is not running -> no vmrun stop/start.
        monkeypatch.setattr(ws, "_is_running", lambda _p: False)

        # Fake qemu-img: write the compressed output where the real tool would.
        def fake_convert(src, dest, target_format):
            Path(dest).write_bytes(b"QCOW2-compressed")
        monkeypatch.setattr(
            VmwareWorkstationPuller, "_run_qemu_img_convert",
            staticmethod(fake_convert),
        )

        puller = VmwareWorkstationPuller()
        desc = puller.list_disks(None, vm)[0]
        dest = tmp_path / "scratch" / "0.qcow2"
        result = puller.convert_on_source(None, vm, desc, dest, cold=True)
        assert dest.is_file()
        assert dest.read_bytes() == b"QCOW2-compressed"
        assert result.source_format == SourceFormat.QCOW2
        assert result.sha256 is not None

    def test_convert_on_source_cold_stops_and_restarts_running_vm(
        self, tmp_path, monkeypatch,
    ):
        from app.services.converter.connectors import vmware_workstation as ws
        from app.services.converter.connectors.vmware_workstation import (
            VmwareWorkstationPuller,
        )
        (tmp_path / "Proxmox").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Proxmox" / "Proxmox.vmdk").write_bytes(b"x" * 1024)
        vmx = _write_vmx(
            tmp_path,
            'scsi0:0.fileName = "Proxmox.vmdk"\n'
            'scsi0:0.deviceType = "scsi-hardDisk"\n',
        )
        vm = _StubVM("Proxmox", {"vmx_path": vmx})

        monkeypatch.setattr(ws, "_is_running", lambda _p: True)
        calls = []
        monkeypatch.setattr(ws, "_vmrun", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(
            VmwareWorkstationPuller, "_run_qemu_img_convert",
            staticmethod(lambda src, dest, fmt: Path(dest).write_bytes(b"Q")),
        )
        puller = VmwareWorkstationPuller()
        desc = puller.list_disks(None, vm)[0]
        puller.convert_on_source(
            None, vm, desc, tmp_path / "s" / "0.qcow2", cold=True,
        )
        # Stopped then started.
        assert calls[0][0] == "stop"
        assert calls[-1][0] == "start"

    def test_service_local_dispatch_rejects_unsupported_type(self):
        from app.models.hypervisor import HypervisorType
        from app.services.converter.protocol import DiskDescriptor
        from app.services.converter.service import ConverterService

        # VIRTUALBOX has no registered converter connector — the registry
        # raises ERR_UNSUPPORTED_HYPERVISOR before any convert_on_source call.
        class _HV:
            type = HypervisorType.VIRTUALBOX

        class _VM:
            source_hypervisor = _HV()

        desc = DiskDescriptor(
            disk_index=0, source_format=SourceFormat.VMDK,
            size_bytes=0, locator="x",
        )
        with pytest.raises(ConversionError) as ei:
            ConverterService._convert_on_source_local(
                _VM(), desc, Path("/tmp/x.qcow2"),
                cold=True, progress_cb=lambda d, t: None,
            )
        assert ei.value.code == "ERR_UNSUPPORTED_HYPERVISOR"


# ---------------------------------------------------------------------------
# Shared connector stubs + base helpers
# ---------------------------------------------------------------------------

class _HVStub:
    """Minimal Hypervisor-shaped stub for connector unit tests."""
    def __init__(self, **kw):
        self.host = kw.get("host", "hv.example.com")
        self.port = kw.get("port")
        self.username = kw.get("username", "root")
        self.password_plain = kw.get("password_plain", "secret")
        self.verify_ssl = kw.get("verify_ssl", False)
        self.ssl_cert_path = kw.get("ssl_cert_path")
        self.connection_config = kw.get("connection_config", {})


class _VMStub2:
    def __init__(self, name="vm1", source_uuid="abc-123"):
        self.name = name
        self.source_uuid = source_uuid


class _DummySSH:
    def close(self):
        pass


class TestBaseHelpers:
    def test_local_qemu_img_convert_success(self, tmp_path, monkeypatch):
        from app.services.converter.connectors import base

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        recorded = {}

        def fake_run(cmd, **kw):
            recorded["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"QCOW2")
            return _R()

        monkeypatch.setattr(base.subprocess, "run", fake_run)
        src = tmp_path / "in.raw"
        src.write_bytes(b"x" * 16)
        dest = tmp_path / "out.qcow2"
        base.local_qemu_img_convert(src, dest, "qcow2")
        assert dest.read_bytes() == b"QCOW2"
        assert "-c" in recorded["cmd"]

    def test_local_qemu_img_convert_failure_maps_error(self, tmp_path, monkeypatch):
        from app.services.converter.connectors import base

        class _R:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr(base.subprocess, "run", lambda *a, **k: _R())
        with pytest.raises(ConversionError) as ei:
            base.local_qemu_img_convert(tmp_path / "a", tmp_path / "b", "qcow2")
        assert ei.value.code == "ERR_OUTPUT_INVALID"

    def test_sha256_file_matches_hashlib(self, tmp_path):
        import hashlib
        from app.services.converter.connectors.base import sha256_file

        f = tmp_path / "f.bin"
        f.write_bytes(b"hello world" * 100)
        assert sha256_file(f) == hashlib.sha256(b"hello world" * 100).hexdigest()


# ---------------------------------------------------------------------------
# KVM connector — convert_on_source
# ---------------------------------------------------------------------------

class TestKvmConnector:
    def test_convert_on_source_stops_converts_pulls_restarts(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import kvm
        from app.services.converter.connectors.kvm import KvmPuller
        from app.services.converter.protocol import DiskDescriptor

        monkeypatch.setattr(kvm, "_ssh_connect", lambda hv: _DummySSH())
        calls = []

        def fake_exec(ssh, cmd, *, timeout=60, expect_rc0=False):
            calls.append(cmd)
            return "4096" if "stat -c %s" in cmd else ""

        monkeypatch.setattr(KvmPuller, "_exec", staticmethod(fake_exec))
        monkeypatch.setattr(
            KvmPuller, "_stop_domain_if_running",
            classmethod(lambda cls, ssh, name: True),
        )

        def fake_pull(ssh, *, remote_path, dest_path, expected_size, host, progress_cb):
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(b"QCOW2-kvm")
            return "kvmsha"

        monkeypatch.setattr(KvmPuller, "_sftp_pull", staticmethod(fake_pull))

        desc = DiskDescriptor(
            disk_index=0, source_format=SourceFormat.RAW,
            size_bytes=4096, locator="/var/lib/libvirt/images/vm1.qcow2",
        )
        dest = tmp_path / "0.qcow2"
        result = KvmPuller().convert_on_source(
            _HVStub(), _VMStub2("vm1"), desc, dest, cold=True,
        )
        assert dest.read_bytes() == b"QCOW2-kvm"
        assert result.source_format == SourceFormat.QCOW2
        assert result.sha256 == "kvmsha"
        # qemu-img convert ran, then the temp was removed and the domain restarted.
        assert any("qemu-img convert" in c for c in calls)
        assert any(c.startswith("rm -f") for c in calls)
        assert any("virsh" in c and "start" in c for c in calls)

    def test_exec_nonzero_raises(self):
        from app.services.converter.connectors.kvm import KvmPuller

        class _Chan:
            def recv_exit_status(self):
                return 2

        class _Stream:
            def __init__(self, data=b""):
                self._data = data
                self.channel = _Chan()

            def read(self):
                return self._data

        class _SSH:
            def exec_command(self, cmd, timeout=60):
                return None, _Stream(b""), _Stream(b"bad")

        with pytest.raises(ConversionError) as ei:
            KvmPuller._exec(_SSH(), "false", expect_rc0=True)
        assert ei.value.code == "ERR_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# oVirt connector
# ---------------------------------------------------------------------------

class TestOvirtConnector:
    def test_normalise_uuid(self):
        from app.services.converter.connectors.ovirt import _normalise_uuid
        assert _normalise_uuid("AB-cd-12") == "abcd12"

    def test_convert_on_source_downloads_then_compresses(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import ovirt
        from app.services.converter.connectors.ovirt import OvirtPuller
        from app.services.converter.protocol import DiskDescriptor

        # Force the SDK path so the SDK-internal monkeypatches below apply.
        monkeypatch.setattr(ovirt, "ovirt_sdk_available", lambda: True)
        monkeypatch.setattr(ovirt, "_connect", lambda hv: _DummySSH())
        monkeypatch.setattr(ovirt, "_close", lambda c: None)

        def fake_download(cls, connection, *, disk_id, dest_path, expected_size, hv, progress_cb):
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(b"RAW-DATA")
            return "rawsha"

        monkeypatch.setattr(OvirtPuller, "_download_disk", classmethod(fake_download))
        monkeypatch.setattr(
            ovirt, "local_qemu_img_convert",
            lambda src, dest, fmt: Path(dest).write_bytes(b"QCOW2-ovirt"),
        )

        desc = DiskDescriptor(
            disk_index=0, source_format=SourceFormat.QCOW2,
            size_bytes=8, locator="disk-uuid-1",
        )
        dest = tmp_path / "0.qcow2"
        result = OvirtPuller().convert_on_source(_HVStub(), _VMStub2(), desc, dest, cold=True)
        assert dest.read_bytes() == b"QCOW2-ovirt"
        assert result.source_format == SourceFormat.QCOW2
        # The intermediate download file is cleaned up.
        assert not (dest.with_suffix(dest.suffix + ".download")).exists()

    def test_pull_disk_live_requires_cold(self):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors.ovirt import OvirtPuller
        from app.services.converter.protocol import DiskDescriptor

        desc = DiskDescriptor(0, SourceFormat.RAW, 0, "d")
        with pytest.raises(ConversionError) as ei:
            OvirtPuller().pull_disk(
                _HVStub(), _VMStub2(), desc, Path("/tmp/x"), cold=False,
            )
        assert ei.value.code == "ERR_VM_RUNNING_NEEDS_COLD"


class _FakeOvirtRest:
    """In-memory stand-in for OvirtRestClient used by REST-path connector tests."""

    def __init__(self, *, vms=None, attachments=None, disks=None, statuses=None):
        self._vms = vms or []
        self._attachments = attachments or []
        self._disks = disks or {}
        self._statuses = list(statuses or ["down"])
        self.stopped = False
        self.started = False
        self.finalized = False
        self.closed = False

    def list_vms(self):
        return self._vms

    def list_disk_attachments(self, vm_id):
        return self._attachments

    def get_disk(self, disk_id):
        return self._disks[disk_id]

    def vm_status(self, vm_id):
        # Pop through the queue, holding the last value once exhausted.
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]

    def stop_vm(self, vm_id):
        self.stopped = True

    def start_vm(self, vm_id):
        self.started = True

    def start_image_transfer(self, disk_id, direction="download"):
        return {"id": "t1"}

    def get_image_transfer(self, transfer_id):
        return {"phase": "transferring", "proxy_url": "https://engine/img/t1"}

    def finalize_image_transfer(self, transfer_id):
        self.finalized = True

    def close(self):
        self.closed = True


class TestOvirtRestConnector:
    def _patch(self, monkeypatch, fake):
        from app.services.converter.connectors import ovirt
        monkeypatch.setattr(ovirt, "ovirt_sdk_available", lambda: False)
        monkeypatch.setattr(ovirt, "OvirtRestClient", lambda hv, **kw: fake)
        return ovirt

    def test_resolve_vm_id_by_uuid(self):
        from app.services.converter.connectors.ovirt import OvirtPuller
        fake = _FakeOvirtRest(vms=[
            {"id": "11111111-0000-0000-0000-000000000000", "name": "other"},
            {"id": "85fd0955-f674-4858-b1eb-c26e569f4fa7", "name": "shiftwise-testvm"},
        ])
        vm = _VMStub2("anything", source_uuid="85FD0955f6744858b1ebc26e569f4fa7")
        assert OvirtPuller._rest_resolve_vm_id(fake, vm) == \
            "85fd0955-f674-4858-b1eb-c26e569f4fa7"

    def test_list_disks_rest(self, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors.ovirt import OvirtPuller
        fake = _FakeOvirtRest(
            vms=[{"id": "vm-1", "name": "shiftwise-testvm"}],
            attachments=[{"disk": {"id": "d99627a7"}}],
            disks={"d99627a7": {"format": "cow", "provisioned_size": 117440512}},
        )
        self._patch(monkeypatch, fake)
        vm = _VMStub2("shiftwise-testvm", source_uuid="vm-1")
        descs = OvirtPuller().list_disks(_HVStub(), vm)
        assert len(descs) == 1
        assert descs[0].source_format == SourceFormat.QCOW2
        assert descs[0].size_bytes == 117440512
        assert descs[0].locator == "d99627a7"

    def test_convert_on_source_rest_stops_downloads_restarts(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors.ovirt import OvirtPuller
        from app.services.converter.protocol import DiskDescriptor

        fake = _FakeOvirtRest(
            vms=[{"id": "vm-1", "name": "shiftwise-testvm"}],
            statuses=["up", "down"],
        )
        ovirt = self._patch(monkeypatch, fake)

        def fake_stream(url, *, dest_path, expected_size, hv, progress_cb):
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(b"RAW-DATA")
            return "rawsha"

        monkeypatch.setattr(OvirtPuller, "_stream_url", staticmethod(fake_stream))
        monkeypatch.setattr(
            ovirt, "local_qemu_img_convert",
            lambda src, dest, fmt: Path(dest).write_bytes(b"QCOW2-rest"),
        )

        desc = DiskDescriptor(0, SourceFormat.QCOW2, 8, "d99627a7")
        dest = tmp_path / "0.qcow2"
        vm = _VMStub2("shiftwise-testvm", source_uuid="vm-1")
        result = OvirtPuller().convert_on_source(_HVStub(), vm, desc, dest, cold=True)

        assert dest.read_bytes() == b"QCOW2-rest"
        assert result.source_format == SourceFormat.QCOW2
        # Running VM was stopped before transfer and restarted after.
        assert fake.stopped and fake.started and fake.finalized
        # Intermediate download file cleaned up.
        assert not dest.with_suffix(dest.suffix + ".download").exists()

    def test_stop_if_running_noop_when_down(self):
        from app.services.converter.connectors.ovirt import OvirtPuller
        fake = _FakeOvirtRest(statuses=["down"])
        assert OvirtPuller._rest_stop_if_running(fake, "vm-1") is False
        assert fake.stopped is False

    def test_await_transfer_url_prefers_proxy(self):
        from app.services.converter.connectors.ovirt import OvirtPuller
        fake = _FakeOvirtRest()
        url = OvirtPuller._rest_await_transfer_url(fake, "t1")
        assert url == "https://engine/img/t1"


# ---------------------------------------------------------------------------
# Hyper-V connector
# ---------------------------------------------------------------------------

class TestHyperVConnector:
    def test_ps_lit_escapes_quotes(self):
        from app.services.converter.connectors.hyperv import _ps_lit
        assert _ps_lit("a'b") == "'a''b'"

    def test_to_unc_maps_drive_to_admin_share(self):
        from app.services.converter.connectors.hyperv import _to_unc
        assert _to_unc("host1", r"C:\VMs\d.vhdx") == r"\\host1\C$\VMs\d.vhdx"

    def test_to_unc_passthrough_unc(self):
        from app.services.converter.connectors.hyperv import _to_unc
        assert _to_unc("h", r"\\srv\share\d.vhdx") == r"\\srv\share\d.vhdx"

    def test_vhd_format_mapping(self):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors.hyperv import _vhd_format
        assert _vhd_format("VHDX") == SourceFormat.VHDX
        assert _vhd_format("vhd") == SourceFormat.VHD

    def test_list_disks_parses_ps_json(self, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import hyperv
        from app.services.converter.connectors.hyperv import HyperVPuller

        payload = (
            '[{"path":"C:\\\\VMs\\\\a.vhdx","size":4096,"filesize":1024,'
            '"format":"VHDX"}]'
        )
        monkeypatch.setattr(hyperv, "_run_ps", lambda hv, script, timeout=120: payload)
        descs = HyperVPuller().list_disks(_HVStub(), _VMStub2())
        assert len(descs) == 1
        assert descs[0].source_format == SourceFormat.VHDX
        assert descs[0].size_bytes == 4096
        assert descs[0].locator.endswith("a.vhdx")

    def test_convert_on_source_local(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import hyperv
        from app.services.converter.connectors.hyperv import HyperVPuller
        from app.services.converter.protocol import DiskDescriptor

        src = tmp_path / "a.vhdx"
        src.write_bytes(b"x" * 32)
        monkeypatch.setattr(HyperVPuller, "_stop_vm_if_running", staticmethod(lambda hv, vm: False))
        monkeypatch.setattr(
            hyperv, "local_qemu_img_convert",
            lambda s, dest, fmt: Path(dest).write_bytes(b"QCOW2-hv"),
        )
        desc = DiskDescriptor(0, SourceFormat.VHDX, 32, str(src))
        dest = tmp_path / "0.qcow2"
        # auth_mode defaults to local -> qemu-img on the local file.
        result = HyperVPuller().convert_on_source(
            _HVStub(connection_config={"auth_mode": "local"}),
            _VMStub2(), desc, dest, cold=True,
        )
        assert dest.read_bytes() == b"QCOW2-hv"
        assert result.source_format == SourceFormat.QCOW2

    def test_convert_on_source_local_reresolves_disk_after_stop(
        self, tmp_path, monkeypatch
    ):
        """When the connector stops the VM, Hyper-V merges the automatic-checkpoint
        .avhdx into the base .vhdx (the .avhdx is deleted). The disk captured while
        running is stale, so convert_on_source must re-resolve the live active disk
        (the base .vhdx) and convert that, not the recorded .avhdx.
        """
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import hyperv
        from app.services.converter.connectors.hyperv import HyperVPuller
        from app.services.converter.protocol import DiskDescriptor

        stale_avhdx = tmp_path / "Migration_ABC.avhdx"   # recorded while running
        base_vhdx = tmp_path / "Migration.vhdx"          # active after the merge
        base_vhdx.write_bytes(b"x" * 64)

        monkeypatch.setattr(
            HyperVPuller, "_stop_vm_if_running", staticmethod(lambda hv, vm: True)
        )
        # After the stop, list_disks reports the merged base .vhdx for index 0.
        monkeypatch.setattr(
            HyperVPuller, "list_disks",
            lambda self, hv, vm: [
                DiskDescriptor(0, SourceFormat.VHDX, 64, str(base_vhdx))
            ],
        )
        monkeypatch.setattr(hyperv, "replay_vhdx_log", lambda s: True)

        converted_from: dict[str, str] = {}

        def _fake_convert(s, dest, fmt):
            converted_from["src"] = str(s)
            Path(dest).write_bytes(b"QCOW2-hv")

        monkeypatch.setattr(hyperv, "local_qemu_img_convert", _fake_convert)
        desc = DiskDescriptor(0, SourceFormat.VHDX, 64, str(stale_avhdx))
        dest = tmp_path / "0.qcow2"
        HyperVPuller().convert_on_source(
            _HVStub(connection_config={"auth_mode": "local"}),
            _VMStub2(), desc, dest, cold=True,
        )
        assert converted_from["src"] == str(base_vhdx), \
            "must convert the re-resolved base .vhdx, not the stale .avhdx"


class TestReplayVhdxLog:
    """``replay_vhdx_log`` is the single-shot openability probe: True only when
    ``qemu-img check -r all`` opens the image and returns 0 (log replayed)."""

    def _result(self, rc, err=""):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=rc, stdout="", stderr=err)

    def test_returns_true_when_check_succeeds(self, tmp_path, monkeypatch):
        from app.services.converter.connectors import base
        monkeypatch.setattr(
            base.subprocess, "run",
            lambda *a, **k: self._result(0, "No errors were found on the image."),
        )
        assert base.replay_vhdx_log(tmp_path / "0.vhdx") is True

    def test_returns_false_when_locked(self, tmp_path, monkeypatch):
        from app.services.converter.connectors import base
        monkeypatch.setattr(
            base.subprocess, "run",
            lambda *a, **k: self._result(1, "Could not open 'x': Unknown error"),
        )
        assert base.replay_vhdx_log(tmp_path / "0.avhdx") is False

    def test_returns_false_when_qemu_missing(self, tmp_path, monkeypatch):
        from app.services.converter.connectors import base

        def _raise(*a, **k):
            raise FileNotFoundError("qemu-img")

        monkeypatch.setattr(base.subprocess, "run", _raise)
        assert base.replay_vhdx_log(tmp_path / "0.vhdx") is False


class TestAwaitLocalSourceAfterStop:
    """``_await_local_source_after_stop`` polls until the re-resolved disk is
    openable, tolerating the merge window where it is locked / changing path."""

    def test_polls_until_disk_ready(self, tmp_path, monkeypatch):
        from app.models.conversion import SourceFormat
        from app.services.converter.connectors import hyperv
        from app.services.converter.connectors.hyperv import HyperVPuller
        from app.services.converter.protocol import DiskDescriptor

        base_vhdx = tmp_path / "Migration.vhdx"
        base_vhdx.write_bytes(b"x" * 16)
        monkeypatch.setattr(
            HyperVPuller, "list_disks",
            lambda self, hv, vm: [DiskDescriptor(0, SourceFormat.VHDX, 16, str(base_vhdx))],
        )
        # replay returns False twice (still merging/locked) then True.
        seq = iter([False, False, True])
        monkeypatch.setattr(hyperv, "replay_vhdx_log", lambda s: next(seq))
        monkeypatch.setattr(hyperv.time, "sleep", lambda *_: None)

        desc = DiskDescriptor(0, SourceFormat.VHDX, 16, str(tmp_path / "stale.avhdx"))
        out = HyperVPuller()._await_local_source_after_stop(
            _HVStub(), _VMStub2(), desc, timeout=10, poll=0,
        )
        assert out == base_vhdx


# ---------------------------------------------------------------------------
# vSphere connector
# ---------------------------------------------------------------------------

class TestVsphereConnector:
    def test_flat_extent_path(self):
        from app.services.converter.connectors.vsphere import _flat_extent_path
        assert _flat_extent_path("[ds1] vm/d.vmdk") == "[ds1] vm/d-flat.vmdk"
        assert _flat_extent_path("[ds1] vm/d-flat.vmdk") == "[ds1] vm/d-flat.vmdk"

    def test_split_ds_path(self):
        from app.services.converter.connectors.vsphere import _split_ds_path
        ds, rel = _split_ds_path("[datastore1] folder/d-flat.vmdk")
        assert ds == "datastore1"
        assert rel == "folder/d-flat.vmdk"

    def test_split_ds_path_rejects_bad(self):
        from app.services.converter.connectors.vsphere import _split_ds_path
        with pytest.raises(ConversionError) as ei:
            _split_ds_path("no-brackets.vmdk")
        assert ei.value.code == "ERR_DISK_NOT_FOUND"

    def test_registry_maps_vsphere_and_esxi_to_vsphere_puller(self):
        from app.models.hypervisor import HypervisorType
        from app.services.converter.connectors import get_puller
        from app.services.converter.connectors.vsphere import VsphereStubPuller

        assert isinstance(get_puller(HypervisorType.VSPHERE), VsphereStubPuller)
        # ESXi enum must resolve to the same connector (additive alias).
        assert isinstance(get_puller(HypervisorType.VMWARE_ESXi), VsphereStubPuller)

    def test_power_off_already_off_makes_no_api_call(self):
        from types import SimpleNamespace
        from app.services.converter.connectors.vsphere import VsphereStubPuller

        def _should_not_be_called():
            raise AssertionError("PowerOffVM_Task must not be called when off")

        vm = SimpleNamespace(
            name="ubuntu",
            runtime=SimpleNamespace(powerState="poweredOff"),
            PowerOffVM_Task=_should_not_be_called,
        )
        assert VsphereStubPuller._power_off_if_running(vm) is False

    def test_power_off_restricted_license_raises_actionable_error(self):
        from types import SimpleNamespace
        from app.services.converter.connectors.vsphere import VsphereStubPuller

        def _restricted():
            # Mimics free/eval ESXi: vim.fault.RestrictedVersion on power ops.
            raise RuntimeError("RestrictedVersion: license prohibits operation")

        vm = SimpleNamespace(
            name="ubuntu",
            runtime=SimpleNamespace(powerState="poweredOn"),
            PowerOffVM_Task=_restricted,
        )
        with pytest.raises(ConversionError) as ei:
            VsphereStubPuller._power_off_if_running(vm)
        assert ei.value.code == "ERR_VM_RUNNING_NEEDS_COLD"
        assert "power" in str(ei.value).lower()

    def test_is_flat_backing_accepts_thin_flat_rejects_sesparse(self):
        # Uses real pyVmomi types so the isinstance guard is verified, not guessed.
        vim = pytest.importorskip("pyVmomi").vim
        from app.services.converter.connectors.vsphere import _is_flat_backing

        flat = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
        flat.thinProvisioned = True  # a thin base disk is still FlatVer2
        sesparse = vim.vm.device.VirtualDisk.SeSparseBackingInfo()  # snapshot

        assert _is_flat_backing(flat) is True
        assert _is_flat_backing(sesparse) is False


# ---------------------------------------------------------------------------
# qemu-img command builder — source-format flag
# ---------------------------------------------------------------------------

class TestQemuImgConvertCmd:
    """Unit-test the pure command-builder so K8s is never involved.

    The helper ``_qemu_img_convert_cmd`` must insert ``-f raw`` into the
    command when ``source_format="raw"`` and must leave the command
    byte-for-byte unchanged for every other value (including omitted /
    empty string / qcow2 / vmdk / vhd).
    """

    def _cmd(self, target_format="qcow2", input_path="/in/0.raw",
             output_path="/out/0.qcow2", source_format=""):
        from app.services.converter.k8s_jobs import _qemu_img_convert_cmd
        return _qemu_img_convert_cmd(
            target_format=target_format,
            input_path=input_path,
            output_path=output_path,
            source_format=source_format,
        )

    # --- raw: must include -f raw -------------------------------------------

    def test_raw_source_inserts_f_flag(self):
        cmd = self._cmd(source_format="raw")
        assert "-f" in cmd
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "raw"

    def test_raw_source_f_flag_is_before_input_path(self):
        cmd = self._cmd(source_format="raw")
        f_idx = cmd.index("-f")
        in_idx = cmd.index("/in/0.raw")
        assert f_idx < in_idx

    def test_raw_source_uppercase_treated_as_raw(self):
        """Case-insensitive: 'RAW' must also trigger -f."""
        cmd = self._cmd(source_format="RAW")
        assert "-f" in cmd

    # --- non-raw: command must be identical to no-source_format call --------

    def test_no_source_format_no_f_flag(self):
        cmd = self._cmd(source_format="")
        assert "-f" not in cmd

    def test_qcow2_source_no_f_flag(self):
        cmd = self._cmd(source_format="qcow2")
        assert "-f" not in cmd

    def test_vmdk_source_no_f_flag(self):
        cmd = self._cmd(source_format="vmdk")
        assert "-f" not in cmd

    def test_vhd_source_no_f_flag(self):
        cmd = self._cmd(source_format="vhd")
        assert "-f" not in cmd

    def test_non_raw_cmd_identical_to_omitted(self):
        """For qcow2/vmdk/vhd the produced list must equal the no-flag baseline."""
        baseline = self._cmd(source_format="")
        for fmt in ("qcow2", "vmdk", "vhd", "vhdx"):
            assert self._cmd(source_format=fmt) == baseline, (
                f"source_format={fmt!r} produced a different command than the baseline"
            )

    # --- qcow2 target: -o compat option still present -----------------------

    def test_qcow2_target_keeps_compat_opts(self):
        cmd = self._cmd(target_format="qcow2", source_format="raw")
        assert "-o" in cmd
        o_idx = cmd.index("-o")
        assert "compat" in cmd[o_idx + 1]

    def test_non_qcow2_target_no_compat_opts(self):
        cmd = self._cmd(target_format="raw", source_format="raw")
        # When target is not qcow2, the compat option value is absent.
        assert not any("compat" in c for c in cmd)
