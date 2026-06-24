"""
P1 tests — transit NFS auto-discovery + tenant namespace auto-create.

Covers:
    - discover_transit_nfs: env-var fast-path, live PV lookup, caching,
      unbound PVC error, non-NFS PV error
    - ensure_tenant_namespace: already exists (no-op), missing (create),
      concurrent 409, 403 on read, 403 on create
    - MigratorService.run: ensure_namespace called before first PVC
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

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
from app.services.migrator.errors import MigratorError
from app.services.migrator.populator_job import PopulatorOutcome


# ---------------------------------------------------------------------------
# Shared fixtures (mirror test_migrator.py)
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
        status=MigrationStatus.CONFIGURING,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{u.tenant_id}",
    )
    db_session.add(mig); db_session.commit()
    g = ConversionGroup(
        tenant_id=u.tenant_id, vm_id=v.id, migration_id=mig.id,
        group_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
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


def _patch_k8s_for_run(monkeypatch):
    """Full mock of the K8s layer needed for MigratorService.run."""
    from app.services.migrator import pvc as pvc_mod
    from app.services.migrator import populator_job as pop_mod
    from app.services.migrator import service as svc_mod

    captured = {}
    captured["ensure_ns"] = MagicMock()
    captured["create_pvc"] = MagicMock(return_value={"metadata": {"name": "x"}})
    captured["submit_populator"] = MagicMock(side_effect=lambda **kw: kw["job_name"])
    captured["wait_populator"] = MagicMock(
        return_value=PopulatorOutcome(succeeded=True, failure_reason=None, container_exit_code=0),
    )
    captured["create_vm"] = MagicMock()
    captured["set_run_strategy"] = MagicMock()
    captured["wait_vmi_running"] = MagicMock()

    monkeypatch.setattr(svc_mod, "ensure_tenant_namespace", captured["ensure_ns"])
    monkeypatch.setattr(pvc_mod, "create_target_pvc", captured["create_pvc"])
    monkeypatch.setattr(svc_mod, "create_target_pvc", captured["create_pvc"])
    monkeypatch.setattr(pop_mod, "submit_populator_job", captured["submit_populator"])
    monkeypatch.setattr(svc_mod, "submit_populator_job", captured["submit_populator"])
    monkeypatch.setattr(pop_mod, "wait_for_populator", captured["wait_populator"])
    monkeypatch.setattr(svc_mod, "wait_for_populator", captured["wait_populator"])

    fake_kv = MagicMock()
    fake_kv.create_vm_from_manifest.side_effect = captured["create_vm"]
    fake_kv.set_vm_run_strategy.side_effect = captured["set_run_strategy"]
    fake_kv.wait_vmi_running.side_effect = captured["wait_vmi_running"]
    monkeypatch.setattr(svc_mod, "get_kubevirt_client", lambda *a, **k: fake_kv)

    return captured


# ---------------------------------------------------------------------------
# Transit NFS auto-discovery
# ---------------------------------------------------------------------------

class TestTransitDiscovery:

    def setup_method(self):
        from app.services.migrator.transit_discovery import clear_cache
        clear_cache()

    def test_explicit_env_vars_bypass_api(self, monkeypatch):
        """Both settings set -> return immediately without any K8s call."""
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "10.0.0.1")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "/exports/transit")

        fake_kv = MagicMock()
        from app.services.migrator.transit_discovery import discover_transit_nfs
        server, path = discover_transit_nfs(fake_kv)

        assert server == "10.0.0.1"
        assert path == "/exports/transit"
        fake_kv.get_pvc.assert_not_called()

    def test_discovers_nfs_from_pv(self, monkeypatch):
        """Empty settings -> reads PVC -> PV -> spec.nfs."""
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_pvc = MagicMock()
        fake_pvc.spec.volume_name = "pv-transit"
        fake_nfs = MagicMock()
        fake_nfs.server = "10.9.21.154"
        fake_nfs.path = "/nfs-storage/openshift-vms"
        fake_pv = MagicMock()
        fake_pv.spec.nfs = fake_nfs
        fake_kv = MagicMock()
        fake_kv.get_pvc.return_value = fake_pvc
        fake_kv.get_pv.return_value = fake_pv

        from app.services.migrator.transit_discovery import discover_transit_nfs
        server, path = discover_transit_nfs(fake_kv)

        assert server == "10.9.21.154"
        assert path == "/nfs-storage/openshift-vms"
        fake_kv.get_pv.assert_called_once_with(name="pv-transit")

    def test_result_is_cached_across_calls(self, monkeypatch):
        """Second call must not hit the K8s API again."""
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_pvc = MagicMock(); fake_pvc.spec.volume_name = "pv-transit"
        fake_nfs = MagicMock(); fake_nfs.server = "1.2.3.4"; fake_nfs.path = "/data"
        fake_pv = MagicMock(); fake_pv.spec.nfs = fake_nfs
        fake_kv = MagicMock()
        fake_kv.get_pvc.return_value = fake_pvc
        fake_kv.get_pv.return_value = fake_pv

        from app.services.migrator.transit_discovery import discover_transit_nfs
        discover_transit_nfs(fake_kv)
        discover_transit_nfs(fake_kv)

        assert fake_kv.get_pvc.call_count == 1

    def test_unbound_pvc_raises(self, monkeypatch):
        """PVC with no volumeName must raise ERR_MIG_INTERNAL."""
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_pvc = MagicMock(); fake_pvc.spec.volume_name = None
        fake_kv = MagicMock(); fake_kv.get_pvc.return_value = fake_pvc

        from app.services.migrator.transit_discovery import discover_transit_nfs
        with pytest.raises(MigratorError) as exc:
            discover_transit_nfs(fake_kv)
        assert exc.value.code == "ERR_MIG_INTERNAL"
        assert "not bound" in exc.value.message.lower()

    def test_pv_without_nfs_spec_raises(self, monkeypatch):
        """PV with no spec.nfs must raise ERR_MIG_INTERNAL."""
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_pvc = MagicMock(); fake_pvc.spec.volume_name = "pv-transit"
        fake_pv = MagicMock(); fake_pv.spec.nfs = None
        fake_kv = MagicMock()
        fake_kv.get_pvc.return_value = fake_pvc
        fake_kv.get_pv.return_value = fake_pv

        from app.services.migrator.transit_discovery import discover_transit_nfs
        with pytest.raises(MigratorError) as exc:
            discover_transit_nfs(fake_kv)
        assert exc.value.code == "ERR_MIG_INTERNAL"

    def test_503_on_pvc_read_is_classified_as_k8s_timeout(self, monkeypatch):
        """5xx during PVC lookup → ERR_MIG_K8S_TIMEOUT (transient, retryable)."""
        from kubernetes.client.rest import ApiException
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_kv = MagicMock()
        fake_kv.get_pvc.side_effect = ApiException(status=503)

        from app.services.migrator.transit_discovery import discover_transit_nfs
        with pytest.raises(MigratorError) as exc:
            discover_transit_nfs(fake_kv)
        assert exc.value.code == "ERR_MIG_K8S_TIMEOUT"
        assert exc.value.is_retryable is True

    def test_403_on_pvc_read_is_classified_as_internal(self, monkeypatch):
        """403 on PVC lookup → ERR_MIG_INTERNAL with RBAC hint in message."""
        from kubernetes.client.rest import ApiException
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_kv = MagicMock()
        fake_kv.get_pvc.side_effect = ApiException(status=403)

        from app.services.migrator.transit_discovery import discover_transit_nfs
        with pytest.raises(MigratorError) as exc:
            discover_transit_nfs(fake_kv)
        assert exc.value.code == "ERR_MIG_INTERNAL"
        assert "pvc/get" in exc.value.message

    def test_partial_env_var_override_warns(self, monkeypatch, caplog):
        """If only one of SERVER/PATH is set, warn and fall back to lookup."""
        import logging
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_SERVER", "10.0.0.1")
        monkeypatch.setattr("app.core.config.settings.MIGRATOR_NFS_PATH", "")

        fake_pvc = MagicMock(); fake_pvc.spec.volume_name = "pv-transit"
        fake_nfs = MagicMock(); fake_nfs.server = "auto.discovered"; fake_nfs.path = "/auto"
        fake_pv = MagicMock(); fake_pv.spec.nfs = fake_nfs
        fake_kv = MagicMock()
        fake_kv.get_pvc.return_value = fake_pvc
        fake_kv.get_pv.return_value = fake_pv

        from app.services.migrator.transit_discovery import discover_transit_nfs
        with caplog.at_level(logging.WARNING, logger="app.services.migrator.transit_discovery"):
            server, path = discover_transit_nfs(fake_kv)

        # Fallback to live lookup happened
        assert server == "auto.discovered"
        assert path == "/auto"
        # Warning was emitted
        assert any("Partial MIGRATOR_NFS_*" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tenant namespace auto-create
# ---------------------------------------------------------------------------

class TestEnsureTenantNamespace:

    def test_existing_namespace_is_noop(self):
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.return_value = MagicMock()

        ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.read_namespace.assert_called_once_with(name="shiftwise-tnt1")
        fake_kv.core_api.create_namespace.assert_not_called()

    def test_missing_namespace_is_created_with_labels(self):
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespace.return_value = MagicMock()

        ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.create_namespace.assert_called_once()
        body = fake_kv.core_api.create_namespace.call_args.kwargs["body"]
        assert body.metadata.name == "shiftwise-tnt1"
        assert body.metadata.labels["app.shiftwise.io/tenant"] == "tnt1"
        assert body.metadata.labels["app.kubernetes.io/managed-by"] == "shiftwise"

    def test_concurrent_create_409_is_silently_ignored(self):
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespace.side_effect = ApiException(status=409)

        ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")  # must not raise

    def test_403_on_read_raises_namespace_forbidden(self):
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=403)

        with pytest.raises(MigratorError) as exc:
            ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_NAMESPACE_FORBIDDEN"

    def test_403_on_create_raises_namespace_forbidden(self):
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespace.side_effect = ApiException(status=403)

        with pytest.raises(MigratorError) as exc:
            ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_NAMESPACE_FORBIDDEN"

    def test_503_on_read_is_classified_as_k8s_timeout(self):
        """5xx during namespace read → ERR_MIG_K8S_TIMEOUT (retryable)."""
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=503)

        with pytest.raises(MigratorError) as exc:
            ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_K8S_TIMEOUT"
        assert exc.value.is_retryable is True

    def test_503_on_create_is_classified_as_k8s_timeout(self):
        """5xx during namespace create → ERR_MIG_K8S_TIMEOUT (retryable)."""
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespace.side_effect = ApiException(status=503)

        with pytest.raises(MigratorError) as exc:
            ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_K8S_TIMEOUT"
        assert exc.value.is_retryable is True

    def test_408_on_read_is_classified_as_k8s_timeout(self):
        """408 Request Timeout is also transient."""
        from kubernetes.client.rest import ApiException
        from app.services.migrator.namespace import ensure_tenant_namespace
        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=408)

        with pytest.raises(MigratorError) as exc:
            ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_K8S_TIMEOUT"

    def test_orchestrator_calls_ensure_ns_before_first_pvc(
        self, db_session, seeded, monkeypatch,
    ):
        """Namespace must be guaranteed before any PVC is created."""
        captured = _patch_k8s_for_run(monkeypatch)
        call_order = []
        captured["ensure_ns"].side_effect = lambda *a, **kw: call_order.append("ns")
        orig_pvc = captured["create_pvc"].side_effect
        captured["create_pvc"].side_effect = (
            lambda **kw: call_order.append("pvc") or {"metadata": {"name": "x"}}
        )

        from app.services.migrator.service import MigratorService
        MigratorService().run(db_session, seeded["migration"].id)

        assert call_order[0] == "ns", (
            f"ensure_namespace must precede create_pvc; order was {call_order}"
        )
        assert "pvc" in call_order
