"""
Adapter unit tests.

Three layers of coverage:
    - Pure logic   : error catalog, job naming
    - Component    : Job manifest shape (no K8s call)
    - Orchestrator : AdapterService.run end-to-end with mocked K8s
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.conversion import (
    ConversionGroup,
    ConversionGroupStatus,
    ConversionJob,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import (
    CompatibilityStatus,
    OSType,
    VirtualMachine,
    VMStatus,
)
from app.services.adapter import errors as adapter_errors
from app.services.adapter.errors import AdapterError
from app.services.adapter.guestfish_job import (
    AdapterOutcome,
    _build_manifest,
    _fixup_script_for_os,
    _LINUX_FIXUP_SCRIPT,
    _WINDOWS_FIXUP_SCRIPT,
    adapter_job_name,
)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

class TestAdapterErrors:
    def test_unknown_code_falls_back_to_internal(self):
        e = AdapterError("ERR_NOT_REAL", "x")
        assert e.code == "ERR_ADAPT_INTERNAL"

    def test_known_code_preserved(self):
        e = AdapterError("ERR_ADAPT_QCOW2_MISSING", "x")
        assert e.code == "ERR_ADAPT_QCOW2_MISSING"

    def test_is_retryable_only_for_transient(self):
        assert AdapterError("ERR_ADAPT_K8S_TIMEOUT", "x").is_retryable is True
        assert AdapterError("ERR_ADAPT_VIRT_CUSTOMIZE_FAILED", "x").is_retryable is False
        assert AdapterError("ERR_ADAPT_NAMESPACE_FORBIDDEN", "x").is_retryable is False

    def test_catalog_has_unique_codes(self):
        codes = list(adapter_errors.ADAPTER_ERROR_CATALOG.keys())
        assert len(codes) == len(set(codes))


class TestAdapterJobNaming:
    def test_name_is_dns_compliant_and_stable(self):
        a = adapter_job_name(42, 0)
        b = adapter_job_name(42, 0)
        assert a == b == "shiftwise-adapt-42-d0"
        assert len(a) <= 63

    def test_name_varies_with_disk(self):
        assert adapter_job_name(42, 0) != adapter_job_name(42, 1)


# ---------------------------------------------------------------------------
# Job manifest
# ---------------------------------------------------------------------------

class TestAdapterJobManifest:
    def _build(self):
        return _build_manifest(
            namespace="shiftwise-tnt1",
            job_name="shiftwise-adapt-1-d0",
            migration_id=1,
            disk_index=0,
            src_relative_path="tnt1/outputs/uuid/0.qcow2",
            nfs_server="10.0.0.9",
            nfs_path="/exports/transit",
            backoff_limit=0,
            active_deadline_seconds=1800,
        )

    def test_basic_shape(self):
        m = self._build()
        assert m["apiVersion"] == "batch/v1"
        assert m["kind"] == "Job"
        assert m["metadata"]["name"] == "shiftwise-adapt-1-d0"
        assert m["metadata"]["namespace"] == "shiftwise-tnt1"

    def test_volume_is_nfs_direct_not_pvc(self):
        m = self._build()
        volumes = m["spec"]["template"]["spec"]["volumes"]
        assert any("nfs" in v for v in volumes)
        assert not any("persistentVolumeClaim" in v for v in volumes)

    def test_nfs_volume_uses_provided_server_and_path(self):
        # Audit C-07: the adapter Job must mount the NFS server/path passed in
        # (discovered from the bound PV), not empty MIGRATOR_NFS_* settings.
        m = self._build()
        volumes = m["spec"]["template"]["spec"]["volumes"]
        nfs = next(v["nfs"] for v in volumes if "nfs" in v)
        assert nfs["server"] == "10.0.0.9"
        assert nfs["path"] == "/exports/transit"

    def test_disk_path_env_is_set_correctly(self):
        m = self._build()
        env = m["spec"]["template"]["spec"]["containers"][0]["env"]
        env_map = {e["name"]: e["value"] for e in env}
        assert env_map["DISK_PATH"] == "/src/tnt1/outputs/uuid/0.qcow2"

    def test_privileged_is_configurable(self):
        # Default in app.core.config is False — libguestfs falls back to TCG
        # without /dev/kvm. The setting is exposed so cluster admins with the
        # KVM device plugin can opt in.
        m = self._build()
        ctx = m["spec"]["template"]["spec"]["containers"][0]["securityContext"]
        assert "privileged" in ctx
        assert isinstance(ctx["privileged"], bool)

    def test_command_is_inline_bash_script(self):
        m = self._build()
        cmd = m["spec"]["template"]["spec"]["containers"][0]["command"]
        assert cmd[0] == "/bin/bash"
        assert cmd[1] == "-c"
        # The inlined script contains the virt-customize call.
        assert "virt-customize" in cmd[2]
        assert "serial-getty@ttyS0" in cmd[2]
        assert "99-shiftwise" in cmd[2]

    def test_windows_manifest_uses_virt_v2v_in_place(self):
        m = _build_manifest(
            namespace="shiftwise-tnt1",
            job_name="shiftwise-adapt-1-d0",
            migration_id=1,
            disk_index=0,
            src_relative_path="tnt1/outputs/uuid/0.qcow2",
            nfs_server="10.0.0.9",
            nfs_path="/exports/transit",
            backoff_limit=0,
            active_deadline_seconds=1800,
            os_type=OSType.WINDOWS,
        )
        script = m["spec"]["template"]["spec"]["containers"][0]["command"][2]
        # Windows path uses virt-v2v-in-place — virt-customize cannot
        # configure DHCP / serial on Windows partitions.
        assert "virt-v2v-in-place" in script
        # The Linux multi-stack DHCP markers must NOT bleed into the
        # Windows path.
        assert "virt-customize" not in script
        assert "serial-getty@ttyS0" not in script

    def test_linux_manifest_does_not_invoke_virt_v2v_in_place(self):
        m = _build_manifest(
            namespace="shiftwise-tnt1",
            job_name="shiftwise-adapt-1-d0",
            migration_id=1,
            disk_index=0,
            src_relative_path="tnt1/outputs/uuid/0.qcow2",
            nfs_server="10.0.0.9",
            nfs_path="/exports/transit",
            backoff_limit=0,
            active_deadline_seconds=1800,
            os_type=OSType.LINUX,
        )
        script = m["spec"]["template"]["spec"]["containers"][0]["command"][2]
        assert "virt-v2v-in-place" not in script
        assert "virt-customize" in script


class TestFixupScriptSelector:
    """Guest-OS family selects the in-pod adapter strategy."""

    def test_windows_picks_virt_v2v_in_place(self):
        assert _fixup_script_for_os(OSType.WINDOWS) is _WINDOWS_FIXUP_SCRIPT

    def test_linux_picks_virt_customize(self):
        assert _fixup_script_for_os(OSType.LINUX) is _LINUX_FIXUP_SCRIPT

    def test_other_and_unknown_default_to_linux(self):
        # Best-effort fallback — the Linux multi-stack script is safe to
        # run on any guest (it only mutates files that exist).
        assert _fixup_script_for_os(OSType.OTHER) is _LINUX_FIXUP_SCRIPT
        assert _fixup_script_for_os(OSType.UNKNOWN) is _LINUX_FIXUP_SCRIPT


# ---------------------------------------------------------------------------
# Orchestrator
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
def seeded(db_session):
    u = User(
        email="t@x", username="t", hashed_password="x",
        tenant_id="tnt1", is_superuser=False,
    )
    db_session.add(u); db_session.commit()
    h = Hypervisor(
        name="kvm1", tenant_id=u.tenant_id, type=HypervisorType.KVM,
        host="kvm.local", username="r",
        status=HypervisorStatus.ACTIVE,
    )
    db_session.add(h); db_session.commit()
    v = VirtualMachine(
        name="prod", tenant_id=u.tenant_id, source_hypervisor_id=h.id,
        source_uuid="u1", cpu_cores=2, memory_mb=2048, disk_gb=10,
        os_type=OSType.LINUX, status=VMStatus.COMPATIBLE,
        compatibility_status=CompatibilityStatus.COMPATIBLE,
    )
    db_session.add(v); db_session.commit()
    mig = Migration(
        tenant_id=u.tenant_id, vm_id=v.id,
        status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{u.tenant_id}",
    )
    db_session.add(mig); db_session.commit()
    g = ConversionGroup(
        tenant_id=u.tenant_id, vm_id=v.id, migration_id=mig.id,
        group_uuid="11111111-2222-3333-4444-555555555555",
        status=ConversionGroupStatus.READY,
        target_format=TargetFormat.QCOW2,
    )
    db_session.add(g); db_session.commit()
    j = ConversionJob(
        tenant_id=u.tenant_id, group_id=g.id, vm_id=v.id,
        disk_index=0,
        source_format=SourceFormat.VMDK, target_format=TargetFormat.QCOW2,
        tool=ConversionTool.QEMU_IMG, status=ConversionStatus.READY,
        output_path="/mnt/transit/tnt1/outputs/uuid/0.qcow2",
        output_size_bytes=10 * 1024 ** 3,
    )
    db_session.add(j); db_session.commit()
    return {"user": u, "vm": v, "migration": mig, "group": g, "job": j}


def _patch_k8s(monkeypatch):
    """Replace every external K8s call with a recording MagicMock."""
    captured = {}

    captured["submit"] = MagicMock(side_effect=lambda **kw: kw["job_name"])
    captured["wait"] = MagicMock(return_value=AdapterOutcome(
        succeeded=True, failure_reason=None, container_exit_code=0,
    ))
    captured["logs"] = MagicMock(return_value="ok")

    from app.services.adapter import guestfish_job as gj_mod
    from app.services.adapter import service as svc_mod

    monkeypatch.setattr(gj_mod, "submit_adapter_job", captured["submit"])
    monkeypatch.setattr(svc_mod, "submit_adapter_job", captured["submit"])
    monkeypatch.setattr(gj_mod, "wait_for_adapter", captured["wait"])
    monkeypatch.setattr(svc_mod, "wait_for_adapter", captured["wait"])
    monkeypatch.setattr(gj_mod, "get_adapter_logs", captured["logs"])
    monkeypatch.setattr(svc_mod, "get_adapter_logs", captured["logs"])

    return captured


class TestAdapterServiceRun:
    def test_happy_path_submits_one_job_per_disk(
        self, db_session, seeded, monkeypatch,
    ):
        captured = _patch_k8s(monkeypatch)

        from app.services.adapter.service import AdapterService

        AdapterService().run(db_session, seeded["migration"].id)

        assert captured["submit"].call_count == 1
        assert captured["wait"].call_count == 1

        # Migration progress was bumped.
        db_session.refresh(seeded["migration"])
        assert seeded["migration"].progress_percentage > 55.0

    def test_windows_vm_threads_os_type_to_submit(
        self, db_session, seeded, monkeypatch,
    ):
        # Flip the seeded VM to Windows — the AdapterService must read
        # that and forward it so the Job runs virt-v2v-in-place instead
        # of virt-customize.
        seeded["vm"].os_type = OSType.WINDOWS
        db_session.commit()
        captured = _patch_k8s(monkeypatch)

        from app.services.adapter.service import AdapterService
        AdapterService().run(db_session, seeded["migration"].id)

        kwargs = captured["submit"].call_args.kwargs
        assert kwargs["os_type"] == OSType.WINDOWS

    def test_linux_vm_threads_os_type_to_submit(
        self, db_session, seeded, monkeypatch,
    ):
        # The seeded VM is already LINUX — verify the kwarg is set
        # (not just defaulted).
        captured = _patch_k8s(monkeypatch)

        from app.services.adapter.service import AdapterService
        AdapterService().run(db_session, seeded["migration"].id)

        kwargs = captured["submit"].call_args.kwargs
        assert kwargs["os_type"] == OSType.LINUX

    def test_two_disks_means_two_jobs(self, db_session, seeded, monkeypatch):
        # Add a second disk in the same group.
        j2 = ConversionJob(
            tenant_id=seeded["user"].tenant_id,
            group_id=seeded["group"].id,
            vm_id=seeded["vm"].id,
            disk_index=1,
            source_format=SourceFormat.VMDK, target_format=TargetFormat.QCOW2,
            tool=ConversionTool.QEMU_IMG, status=ConversionStatus.READY,
            output_path="/mnt/transit/tnt1/outputs/uuid/1.qcow2",
            output_size_bytes=2 * 1024 ** 3,
        )
        db_session.add(j2); db_session.commit()

        captured = _patch_k8s(monkeypatch)

        from app.services.adapter.service import AdapterService
        AdapterService().run(db_session, seeded["migration"].id)

        assert captured["submit"].call_count == 2

    def test_failure_raises_typed_error(self, db_session, seeded, monkeypatch):
        captured = _patch_k8s(monkeypatch)
        captured["wait"].return_value = AdapterOutcome(
            succeeded=False, failure_reason="OOMKilled", container_exit_code=137,
        )

        from app.services.adapter.service import AdapterService

        with pytest.raises(AdapterError) as excinfo:
            AdapterService().run(db_session, seeded["migration"].id)
        # Non-zero exit -> mapped to virt-customize failure.
        assert excinfo.value.code == "ERR_ADAPT_VIRT_CUSTOMIZE_FAILED"

    def test_timeout_maps_to_k8s_timeout(self, db_session, seeded, monkeypatch):
        captured = _patch_k8s(monkeypatch)
        captured["wait"].return_value = AdapterOutcome(
            succeeded=False, failure_reason="DeadlineExceeded",
            container_exit_code=None,
        )

        from app.services.adapter.service import AdapterService

        with pytest.raises(AdapterError) as excinfo:
            AdapterService().run(db_session, seeded["migration"].id)
        assert excinfo.value.code == "ERR_ADAPT_K8S_TIMEOUT"

    def test_no_jobs_raises_qcow2_missing(self, db_session, seeded, monkeypatch):
        # Remove all completed jobs.
        seeded["job"].status = ConversionStatus.FAILED
        seeded["job"].output_path = None
        db_session.commit()
        _patch_k8s(monkeypatch)

        from app.services.adapter.service import AdapterService

        with pytest.raises(AdapterError) as excinfo:
            AdapterService().run(db_session, seeded["migration"].id)
        assert excinfo.value.code == "ERR_ADAPT_QCOW2_MISSING"
