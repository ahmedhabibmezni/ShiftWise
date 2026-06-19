"""
Migrator unit tests.

Three layers of coverage:
    - Pure logic   : vm_manifest builder, pvc sizing, error catalog round-trip
    - Component    : populator manifest shape (no K8s call)
    - Orchestrator : MigratorService.run end-to-end with mocks for the
                     KubeVirt client + populator + DB

We do NOT spin up a real cluster — every K8s call is monkey-patched.
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
from app.services.migrator import errors as migrator_errors
from app.services.migrator.errors import MigratorError
from app.services.migrator.populator_job import (
    PopulatorOutcome,
    populator_job_name,
)
from app.services.migrator.pvc import compute_pvc_size_bytes, target_pvc_name
from app.services.migrator.vm_manifest import (
    DiskSpec,
    build_virtual_machine,
    sanitize_vm_name,
)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

class TestSanitizeVmName:
    def test_lowercases_and_replaces_invalid_chars(self):
        assert sanitize_vm_name("My_VM 01!", "fb") == "my-vm-01"

    def test_collapses_multiple_dashes(self):
        assert sanitize_vm_name("a___b---c", "fb") == "a-b-c"

    def test_strips_leading_and_trailing_dashes(self):
        assert sanitize_vm_name("---weird---", "fb") == "weird"

    def test_falls_back_when_empty(self):
        assert sanitize_vm_name("!!!", "fallback-1") == "fallback-1"
        assert sanitize_vm_name("", "fallback-1") == "fallback-1"

    def test_truncates_to_63_chars(self):
        long = "a" * 100
        out = sanitize_vm_name(long, "fb")
        assert len(out) <= 63


class TestComputePvcSize:
    def test_returns_min_for_zero_or_none(self):
        assert compute_pvc_size_bytes(None) >= 1024 * 1024 * 1024
        assert compute_pvc_size_bytes(0) >= 1024 * 1024 * 1024

    def test_adds_headroom(self):
        size = compute_pvc_size_bytes(10 * 1024 ** 3)  # 10 GiB
        assert size > 10 * 1024 ** 3
        # 15% headroom
        assert size <= int(10 * 1024 ** 3 * 1.20)


class TestPvcAndJobNaming:
    def test_pvc_name_is_stable(self):
        a = target_pvc_name(42, 0)
        b = target_pvc_name(42, 0)
        assert a == b == "shiftwise-mig-42-disk-0"

    def test_pvc_name_varies_with_disk(self):
        assert target_pvc_name(42, 0) != target_pvc_name(42, 1)

    def test_job_name_is_dns_compliant(self):
        n = populator_job_name(42, 0)
        assert len(n) <= 63
        assert n.replace("-", "").replace("d", "0").isalnum() or "-" in n


class TestErrorsCatalog:
    def test_unknown_code_falls_back_to_internal(self):
        e = MigratorError("ERR_DOES_NOT_EXIST", "x")
        assert e.code == "ERR_MIG_INTERNAL"

    def test_known_code_preserved(self):
        e = MigratorError("ERR_MIG_QCOW2_MISSING", "x")
        assert e.code == "ERR_MIG_QCOW2_MISSING"

    def test_is_retryable_only_for_transient(self):
        assert MigratorError("ERR_MIG_K8S_TIMEOUT", "x").is_retryable is True
        assert MigratorError("ERR_MIG_QCOW2_CORRUPT", "x").is_retryable is False
        assert MigratorError("ERR_MIG_NAMESPACE_FORBIDDEN", "x").is_retryable is False

    def test_every_catalog_entry_has_unique_code(self):
        codes = list(migrator_errors.MIGRATOR_ERROR_CATALOG.keys())
        assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# VM manifest builder
# ---------------------------------------------------------------------------

class TestBuildVirtualMachine:
    def _disks(self):
        return [
            DiskSpec(disk_index=0, pvc_name="pvc-0", is_boot=True),
            DiskSpec(disk_index=1, pvc_name="pvc-1", is_boot=False),
        ]

    def test_basic_shape(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=2, memory_mb=4096,
            disks=self._disks(), os_type=OSType.LINUX,
        )
        assert m["apiVersion"] == "kubevirt.io/v1"
        assert m["kind"] == "VirtualMachine"
        assert m["metadata"]["name"] == "vm1"
        assert m["metadata"]["namespace"] == "ns"
        # Halted on create — orchestrator flips to Always after success.
        assert m["spec"]["runStrategy"] == "Halted"

    def test_disk_devices_and_volumes_match_count(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=1, memory_mb=512,
            disks=self._disks(), os_type=OSType.LINUX,
        )
        disks = m["spec"]["template"]["spec"]["domain"]["devices"]["disks"]
        volumes = m["spec"]["template"]["spec"]["volumes"]
        assert len(disks) == 2
        assert len(volumes) == 2

    def test_boot_order_only_on_disk_zero(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=1, memory_mb=512,
            disks=self._disks(), os_type=OSType.LINUX,
        )
        disks = m["spec"]["template"]["spec"]["domain"]["devices"]["disks"]
        assert disks[0]["bootOrder"] == 1
        assert "bootOrder" not in disks[1]

    def test_pod_network_interface_defaults_to_masquerade(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=1, memory_mb=512,
            disks=self._disks(), os_type=OSType.LINUX,
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        ifaces = m["spec"]["template"]["spec"]["domain"]["devices"]["interfaces"]
        assert ifaces[0]["masquerade"] == {}
        assert ifaces[0]["macAddress"] == "aa:bb:cc:dd:ee:ff"
        assert m["spec"]["template"]["spec"]["networks"][0]["pod"] == {}

    def test_windows_gets_tablet_input(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=2, memory_mb=4096,
            disks=self._disks(), os_type=OSType.WINDOWS,
        )
        devices = m["spec"]["template"]["spec"]["domain"]["devices"]
        assert any(i.get("type") == "tablet" for i in devices.get("inputs", []))

    def test_linux_does_not_get_tablet(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=2, memory_mb=4096,
            disks=self._disks(), os_type=OSType.LINUX,
        )
        devices = m["spec"]["template"]["spec"]["domain"]["devices"]
        assert "inputs" not in devices

    def test_efi_firmware_emits_bootloader_block(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=2, memory_mb=4096,
            disks=self._disks(), os_type=OSType.LINUX,
            firmware="efi",
        )
        domain = m["spec"]["template"]["spec"]["domain"]
        assert domain["firmware"]["bootloader"]["efi"]["secureBoot"] is False

    def test_efi_firmware_is_case_insensitive(self):
        m = build_virtual_machine(
            name="vm1", namespace="ns",
            cpu_cores=2, memory_mb=4096,
            disks=self._disks(), os_type=OSType.LINUX,
            firmware="EFI",
        )
        domain = m["spec"]["template"]["spec"]["domain"]
        assert "firmware" in domain

    def test_bios_or_unknown_firmware_omits_bootloader_block(self):
        # SeaBIOS default — no firmware block (back-compat with BIOS guests
        # like the Alpine/Proxmox path that already booted).
        for fw in ("bios", None, ""):
            m = build_virtual_machine(
                name="vm1", namespace="ns",
                cpu_cores=2, memory_mb=4096,
                disks=self._disks(), os_type=OSType.LINUX,
                firmware=fw,
            )
            domain = m["spec"]["template"]["spec"]["domain"]
            assert "firmware" not in domain

    def test_rejects_no_disks(self):
        with pytest.raises(ValueError):
            build_virtual_machine(
                name="vm1", namespace="ns",
                cpu_cores=1, memory_mb=512,
                disks=[], os_type=OSType.LINUX,
            )

    def test_rejects_invalid_cpu_or_memory(self):
        with pytest.raises(ValueError):
            build_virtual_machine(
                name="vm1", namespace="ns",
                cpu_cores=0, memory_mb=512,
                disks=self._disks(), os_type=OSType.LINUX,
            )
        with pytest.raises(ValueError):
            build_virtual_machine(
                name="vm1", namespace="ns",
                cpu_cores=1, memory_mb=64,
                disks=self._disks(), os_type=OSType.LINUX,
            )


# ---------------------------------------------------------------------------
# Orchestrator — happy path with full mocking
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
        status=HypervisorStatus.ACTIVE, total_vms_discovered=0,
    )
    db_session.add(h); db_session.commit()
    v = VirtualMachine(
        name="prod-app", tenant_id=u.tenant_id, source_hypervisor_id=h.id,
        source_uuid="u1", cpu_cores=2, memory_mb=2048, disk_gb=20,
        os_type=OSType.LINUX, os_name="Ubuntu 22.04", os_version="22.04",
        status=VMStatus.COMPATIBLE,
        compatibility_status=CompatibilityStatus.COMPATIBLE,
    )
    db_session.add(v); db_session.commit()
    mig = Migration(
        tenant_id=u.tenant_id, vm_id=v.id,
        status=MigrationStatus.CONFIGURING,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{u.tenant_id}",
        target_storage_class="nfs-client",
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
        source_format=SourceFormat.VMDK,
        target_format=TargetFormat.QCOW2,
        tool=ConversionTool.QEMU_IMG,
        status=ConversionStatus.READY,
        output_path="/mnt/shiftwise-transit/tnt1/outputs/uuid/0.qcow2",
        output_size_bytes=10 * 1024 ** 3,
    )
    db_session.add(j); db_session.commit()
    return {"user": u, "vm": v, "migration": mig, "group": g, "job": j}


def _patch_k8s_layer(monkeypatch):
    """Replace every external K8s call with a recording MagicMock.

    Returns the captured handles so tests can assert on the orchestrator's
    interaction with the K8s side.
    """
    captured = {}

    captured["create_pvc"] = MagicMock(return_value={"metadata": {"name": "x"}})
    captured["submit_populator"] = MagicMock(side_effect=lambda **kw: kw["job_name"])
    captured["wait_populator"] = MagicMock(
        return_value=PopulatorOutcome(
            succeeded=True, failure_reason=None, container_exit_code=0,
        ),
    )
    captured["create_vm"] = MagicMock()
    captured["set_run_strategy"] = MagicMock()
    captured["wait_vmi_running"] = MagicMock()

    from app.services.migrator import pvc as pvc_mod
    from app.services.migrator import populator_job as pop_mod
    from app.services.migrator import service as svc_mod

    monkeypatch.setattr(pvc_mod, "create_target_pvc", captured["create_pvc"])
    monkeypatch.setattr(svc_mod, "create_target_pvc", captured["create_pvc"])
    monkeypatch.setattr(pop_mod, "submit_populator_job", captured["submit_populator"])
    monkeypatch.setattr(svc_mod, "submit_populator_job", captured["submit_populator"])
    monkeypatch.setattr(pop_mod, "wait_for_populator", captured["wait_populator"])
    monkeypatch.setattr(svc_mod, "wait_for_populator", captured["wait_populator"])

    captured["populator_logs"] = MagicMock(return_value="")
    monkeypatch.setattr(pop_mod, "get_populator_logs", captured["populator_logs"])
    monkeypatch.setattr(svc_mod, "get_populator_logs", captured["populator_logs"])

    captured["ensure_ns"] = MagicMock()
    monkeypatch.setattr(svc_mod, "ensure_tenant_namespace", captured["ensure_ns"])

    fake_kv = MagicMock()
    fake_kv.create_vm_from_manifest.side_effect = captured["create_vm"]
    fake_kv.set_vm_run_strategy.side_effect = captured["set_run_strategy"]
    fake_kv.wait_vmi_running.side_effect = captured["wait_vmi_running"]
    monkeypatch.setattr(svc_mod, "get_kubevirt_client", lambda *a, **k: fake_kv)

    return captured


class TestMigratorServiceRun:
    def test_happy_path_drives_to_completed(self, db_session, seeded, monkeypatch):
        captured = _patch_k8s_layer(monkeypatch)

        from app.services.migrator.service import MigratorService

        terminal = MigratorService().run(db_session, seeded["migration"].id)

        assert terminal == MigrationStatus.COMPLETED
        # PVC + populator submitted exactly once for the single disk.
        assert captured["create_pvc"].call_count == 1
        assert captured["submit_populator"].call_count == 1
        # VM creation flow.
        assert captured["create_vm"].call_count == 1
        assert captured["set_run_strategy"].call_count == 1
        assert captured["wait_vmi_running"].call_count == 1

        db_session.refresh(seeded["migration"])
        assert seeded["migration"].status == MigrationStatus.COMPLETED
        assert seeded["migration"].progress_percentage == 100.0
        # VM row also stamped MIGRATED with OpenShift coordinates.
        db_session.refresh(seeded["vm"])
        assert seeded["vm"].status == VMStatus.MIGRATED
        assert seeded["vm"].openshift_namespace == f"shiftwise-{seeded['user'].tenant_id}"
        assert seeded["vm"].openshift_vm_name == "prod-app"

    def test_populator_failure_raises_typed_error(
        self, db_session, seeded, monkeypatch,
    ):
        captured = _patch_k8s_layer(monkeypatch)
        captured["wait_populator"].return_value = PopulatorOutcome(
            succeeded=False, failure_reason="OomKilled", container_exit_code=137,
        )

        from app.services.migrator.service import MigratorService

        with pytest.raises(MigratorError) as excinfo:
            MigratorService().run(db_session, seeded["migration"].id)
        # exit_code 137 is non-zero -> we map it to QCOW2_CORRUPT today.
        assert excinfo.value.code == "ERR_MIG_QCOW2_CORRUPT"

    def test_enospc_populator_maps_to_pvc_too_small(
        self, db_session, seeded, monkeypatch,
    ):
        """A populator that died `No space left on device` is a too-small PVC,
        not a corrupt source — surface the actionable code."""
        captured = _patch_k8s_layer(monkeypatch)
        captured["wait_populator"].return_value = PopulatorOutcome(
            succeeded=False, failure_reason="BackoffLimitExceeded",
            container_exit_code=1,
        )
        captured["populator_logs"].return_value = (
            "(98.62/100%)qemu-img: error while writing at byte 11907825664: "
            "No space left on device"
        )

        from app.services.migrator.service import MigratorService

        with pytest.raises(MigratorError) as excinfo:
            MigratorService().run(db_session, seeded["migration"].id)
        assert excinfo.value.code == "ERR_MIG_PVC_TOO_SMALL"

    def test_pvc_sized_from_virtual_not_compressed_size(
        self, db_session, seeded, monkeypatch,
    ):
        """The PVC must be sized from the disk's raw virtual size
        (source_size_bytes), not the small compressed qcow2 file."""
        captured = _patch_k8s_layer(monkeypatch)
        # Provisioned 12 GiB disk that compressed to a 2 GiB qcow2.
        seeded["job"].source_size_bytes = 12 * 1024 ** 3
        seeded["job"].output_size_bytes = 2 * 1024 ** 3
        db_session.commit()

        from app.services.migrator.service import MigratorService

        MigratorService().run(db_session, seeded["migration"].id)

        size_bytes = captured["create_pvc"].call_args.kwargs["size_bytes"]
        # Must cover the 12 GiB virtual size, not the 2 GiB compressed file.
        assert size_bytes >= 12 * 1024 ** 3

    def test_missing_qcow2_raises_typed_error(
        self, db_session, seeded, monkeypatch,
    ):
        # Wipe the only completed job so the orchestrator finds none.
        seeded["job"].status = ConversionStatus.FAILED
        seeded["job"].output_path = None
        db_session.commit()
        _patch_k8s_layer(monkeypatch)

        from app.services.migrator.service import MigratorService

        with pytest.raises(MigratorError) as excinfo:
            MigratorService().run(db_session, seeded["migration"].id)
        assert excinfo.value.code == "ERR_MIG_QCOW2_MISSING"
