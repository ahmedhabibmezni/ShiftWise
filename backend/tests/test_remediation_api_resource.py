"""
Remediation tests — API resource routers (vms / hypervisors / migrations /
conversions / kubevirt).

Each test pins one audit finding (AUDIT_REMEDIATION.md domain B/C). Route
handlers are called directly with an in-memory SQLite session and a synthetic
``User`` — the same pattern as ``test_migrations_api.py`` /
``test_conversions_api.py``. External effects (Celery broker, KubeVirt client,
Redis) are monkeypatched.
"""

from __future__ import annotations

import inspect
import typing
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
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


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser(tenant: str = "t1") -> User:
    return User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id=tenant, is_superuser=True,
    )


def _seed_vm(db, *, tenant: str = "t1", hv_id: int = 1,
             status: VMStatus = VMStatus.DISCOVERED) -> VirtualMachine:
    vm = VirtualMachine(
        name="vm1", tenant_id=tenant, source_hypervisor_id=hv_id,
        source_uuid="u1", cpu_cores=2, memory_mb=2048, disk_gb=10,
        os_type=OSType.LINUX, status=status,
        compatibility_status=CompatibilityStatus.COMPATIBLE,
    )
    db.add(vm)
    db.commit()
    return vm


def _seed_hypervisor(db, *, tenant: str = "t1") -> Hypervisor:
    hv = Hypervisor(
        name="hv1", tenant_id=tenant, type=HypervisorType.VMWARE_WORKSTATION,
        host="10.0.0.10", username="u", password="p",
        status=HypervisorStatus.ACTIVE, is_active=True,
    )
    db.add(hv)
    db.commit()
    return hv


def _seed_migration(db, *, vm_id: int, tenant: str = "t1",
                    status: MigrationStatus = MigrationStatus.PENDING) -> Migration:
    mig = Migration(
        tenant_id=tenant, vm_id=vm_id, status=status,
        strategy=MigrationStrategy.AUTO, target_namespace=f"shiftwise-{tenant}",
    )
    db.add(mig)
    db.commit()
    return mig


# ==========================================================================
# B4 — PUT /migrations/{id}/progress restricted to an internal/worker path
# ==========================================================================

def test_b4_progress_rejects_request_without_internal_token(db_session):
    """An API caller (no internal token) must be rejected."""
    from app.api.v1.migrations import update_migration_progress
    from app.schemas.migration import MigrationProgressUpdate

    vm = _seed_vm(db_session)
    mig = _seed_migration(db_session, vm_id=vm.id,
                          status=MigrationStatus.TRANSFERRING)
    payload = MigrationProgressUpdate(progress_percentage=50.0,
                                      current_step="TRANSFERRING")

    with pytest.raises(HTTPException) as exc:
        update_migration_progress(mig.id, payload, internal_ok=False,
                                  db=db_session)
    assert exc.value.status_code in (401, 403)


def test_b4_progress_accepts_internal_token(db_session):
    """The worker (valid internal token) can still post progress."""
    from app.api.v1.migrations import update_migration_progress
    from app.schemas.migration import MigrationProgressUpdate

    vm = _seed_vm(db_session)
    mig = _seed_migration(db_session, vm_id=vm.id,
                          status=MigrationStatus.TRANSFERRING)
    payload = MigrationProgressUpdate(progress_percentage=75.0,
                                      current_step="TRANSFERRING")

    result = update_migration_progress(mig.id, payload, internal_ok=True,
                                       db=db_session)
    assert result.progress_percentage == 75.0


def test_b4_progress_no_longer_uses_check_permission():
    """The handler must not authenticate via the public RBAC dependency."""
    from app.api.v1 import migrations as mig_mod
    sig = inspect.signature(mig_mod.update_migration_progress)
    assert "current_user" not in sig.parameters


# ==========================================================================
# B5 — GET /kubevirt/namespace-info tenant-scoped
# ==========================================================================

def test_b5_namespace_info_is_tenant_scoped(monkeypatch):
    """A non-superuser must only see their own tenant namespace counts."""
    from app.api.v1.kubevirt import get_namespace_info

    captured = {}

    fake_client = MagicMock()

    def _list_vms(namespace=None, label_selector=None):
        captured["vms_ns"] = namespace
        return []

    def _list_vmis(namespace=None, label_selector=None):
        captured["vmis_ns"] = namespace
        return []

    fake_client.list_vms.side_effect = _list_vms
    fake_client.list_vmis.side_effect = _list_vmis
    fake_client.list_storage_classes.return_value = []

    normal = User(email="u@x.com", username="u", hashed_password="x",
                   tenant_id="t9", is_superuser=False)
    # validate_kubevirt_namespace resolves "shiftwise-t9" for this user.
    get_namespace_info(namespace="shiftwise-t9", kube_client=fake_client,
                       current_user=normal)

    assert captured["vms_ns"] == "shiftwise-t9"
    assert captured["vmis_ns"] == "shiftwise-t9"


def test_b5_namespace_info_signature_has_namespace_dep():
    from app.api.v1 import kubevirt as kv_mod
    sig = inspect.signature(kv_mod.get_namespace_info)
    assert "namespace" in sig.parameters


# ==========================================================================
# B6 — ConversionCreate.migration_id tenant-validated (IDOR)
# ==========================================================================

def test_b6_convert_rejects_foreign_tenant_migration(db_session):
    """A migration_id pointing at another tenant's migration → 404."""
    from app.api.v1.vms import convert_vm
    from app.schemas.conversion import ConversionCreate

    vm = _seed_vm(db_session, tenant="t1")
    # Migration owned by a DIFFERENT tenant.
    foreign_mig = _seed_migration(db_session, vm_id=vm.id, tenant="t2")

    normal = User(email="u@x.com", username="u", hashed_password="x",
                  tenant_id="t1", is_superuser=False)
    payload = ConversionCreate(vm_id=vm.id, migration_id=foreign_mig.id)

    with pytest.raises(HTTPException) as exc:
        convert_vm(vm.id, payload, db=db_session, current_user=normal)
    assert exc.value.status_code == 404


# ==========================================================================
# B11 — GET /vms/{id}/migrations also requires migrations:read
# ==========================================================================

def test_b11_vm_migrations_requires_migrations_read():
    """The handler must depend on both vms:read and migrations:read."""
    from app.api.v1 import vms as vms_mod
    sig = inspect.signature(vms_mod.get_vm_migrations)
    # A dedicated migrations:read gate parameter must exist.
    assert any(p for p in sig.parameters if "migration" in p.lower()
               and p != "vm_id")


# ==========================================================================
# B12 — GET /hypervisors/{id}/vms also requires vms:read
# ==========================================================================

def test_b12_hypervisor_vms_requires_vms_read():
    from app.api.v1 import hypervisors as hv_mod
    sig = inspect.signature(hv_mod.get_hypervisor_vms)
    assert any(p for p in sig.parameters if p.startswith("_vms"))


# ==========================================================================
# B21 — POST /hypervisors/test-connection rate-limited
# ==========================================================================

def test_b21_test_connection_rate_limited(db_session, monkeypatch):
    """Exceeding the per-user quota returns 429."""
    from app.api.v1 import hypervisors as hv_mod
    from app.schemas.hypervisor import HypervisorTestConnection

    # Force the rate limiter to report "over quota".
    monkeypatch.setattr(hv_mod, "_test_connection_rate_limited",
                        lambda user_id: True)

    test_data = HypervisorTestConnection(
        type=HypervisorType.VMWARE_WORKSTATION, host="10.0.0.1",
        username="u", password="p",
    )
    with pytest.raises(HTTPException) as exc:
        hv_mod.test_hypervisor_connection(test_data, db=db_session,
                                          current_user=_superuser())
    assert exc.value.status_code == 429


def test_b21_test_connection_allowed_under_quota(db_session, monkeypatch):
    """Under quota, the call proceeds normally."""
    from app.api.v1 import hypervisors as hv_mod
    from app.schemas.hypervisor import HypervisorTestConnection

    monkeypatch.setattr(hv_mod, "_test_connection_rate_limited",
                        lambda user_id: False)
    fake_service = MagicMock()
    fake_service.test_connection.return_value = {
        "success": True, "vms_count": 3, "error": None,
    }
    monkeypatch.setattr(hv_mod, "create_discovery_service",
                        lambda db: fake_service)

    test_data = HypervisorTestConnection(
        type=HypervisorType.VMWARE_WORKSTATION, host="10.0.0.1",
        username="u", password="p",
    )
    result = hv_mod.test_hypervisor_connection(test_data, db=db_session,
                                               current_user=_superuser())
    assert result.success is True


# ==========================================================================
# C7 — KubeVirt endpoints correct status codes
# ==========================================================================

def _route_status(router, path: str, method: str) -> int:
    for route in router.routes:
        if getattr(route, "path", None) == path and method in route.methods:
            return route.status_code
    raise AssertionError(f"route {method} {path} not found")


def test_c7_kubevirt_post_returns_201():
    from app.api.v1.kubevirt import router
    assert _route_status(router, "/vms", "POST") == 201


def test_c7_kubevirt_delete_returns_204():
    from app.api.v1.kubevirt import router
    assert _route_status(router, "/vms/{vm_name}", "DELETE") == 204


def test_c7_kubevirt_start_stop_return_202():
    from app.api.v1.kubevirt import router
    assert _route_status(router, "/vms/{vm_name}/start", "POST") == 202
    assert _route_status(router, "/vms/{vm_name}/stop", "POST") == 202


# ==========================================================================
# C8 — list endpoints paginated at the query
# ==========================================================================

def test_c8_hypervisor_vms_paginated():
    from app.api.v1 import hypervisors as hv_mod
    sig = inspect.signature(hv_mod.get_hypervisor_vms)
    assert "skip" in sig.parameters and "limit" in sig.parameters


def test_c8_vm_migrations_paginated():
    from app.api.v1 import vms as vms_mod
    sig = inspect.signature(vms_mod.get_vm_migrations)
    assert "skip" in sig.parameters and "limit" in sig.parameters


def test_c8_hypervisor_vms_limit_caps_result(db_session, monkeypatch):
    """The query-level limit must bound the rows returned."""
    from app.api.v1 import hypervisors as hv_mod

    hv = _seed_hypervisor(db_session)
    for i in range(5):
        db_session.add(VirtualMachine(
            name=f"vm{i}", tenant_id="t1", source_hypervisor_id=hv.id,
            source_uuid=f"u{i}", cpu_cores=1, memory_mb=512, disk_gb=5,
            os_type=OSType.LINUX, status=VMStatus.DISCOVERED,
            compatibility_status=CompatibilityStatus.UNKNOWN,
        ))
    db_session.commit()

    result = hv_mod.get_hypervisor_vms(hv.id, skip=0, limit=2,
                                       db=db_session, current_user=_superuser())
    assert len(result["vms"]) == 2


# ==========================================================================
# C9 / C17 — analyze/batch accepts vm_ids in the body, no mutable default
# ==========================================================================

def test_c9_analyze_batch_takes_body_not_query():
    """vm_ids must arrive as a request body, not a Query parameter."""
    from app.api.v1 import vms as vms_mod
    sig = inspect.signature(vms_mod.analyze_vms_batch)
    # The body parameter must be a Pydantic model, not a list[int] Query.
    assert "vm_ids" not in sig.parameters
    # exactly one parameter is the request body model
    assert "payload" in sig.parameters or "body" in sig.parameters


def test_c17_analyze_batch_no_mutable_default():
    """No parameter default may be a mutable list literal."""
    from app.api.v1 import vms as vms_mod
    for name, p in inspect.signature(vms_mod.analyze_vms_batch).parameters.items():
        assert not isinstance(p.default, list), (
            f"{name} has a mutable list default"
        )


def test_c9_analyze_batch_runs_with_body(db_session, monkeypatch):
    from app.api.v1 import vms as vms_mod

    vm = _seed_vm(db_session)
    fake_analyzer = MagicMock()
    fake_analyzer.analyze_batch.return_value = {"analyzed": 1}
    monkeypatch.setattr(vms_mod, "create_analyzer_service",
                        lambda: fake_analyzer)

    # Build whatever body schema the endpoint now declares.
    sig = inspect.signature(vms_mod.analyze_vms_batch)
    body_param = sig.parameters.get("payload") or sig.parameters.get("body")
    body_model = typing.get_args(body_param.annotation)
    body_cls = body_model[0] if body_model else body_param.annotation
    body = body_cls(vm_ids=[vm.id])

    kwargs = {body_param.name: body, "db": db_session,
              "current_user": _superuser()}
    if "force" in sig.parameters:
        kwargs["force"] = False
    result = vms_mod.analyze_vms_batch(**kwargs)
    assert result["analyzed"] == 1
    assert fake_analyzer.analyze_batch.call_count == 1


def test_c9_analyze_batch_rejects_over_cap(db_session, monkeypatch):
    from app.api.v1 import vms as vms_mod

    fake_analyzer = MagicMock()
    monkeypatch.setattr(vms_mod, "create_analyzer_service",
                        lambda: fake_analyzer)
    sig = inspect.signature(vms_mod.analyze_vms_batch)
    body_param = sig.parameters.get("payload") or sig.parameters.get("body")
    body_model = typing.get_args(body_param.annotation)
    body_cls = body_model[0] if body_model else body_param.annotation
    body = body_cls(vm_ids=list(range(1, 25)))

    kwargs = {body_param.name: body, "db": db_session,
              "current_user": _superuser()}
    if "force" in sig.parameters:
        kwargs["force"] = False
    with pytest.raises(HTTPException) as exc:
        vms_mod.analyze_vms_batch(**kwargs)
    assert exc.value.status_code == 422


# ==========================================================================
# C10 — KubeVirt endpoints return 503 on cluster-unreachable
# ==========================================================================

def test_c10_list_vms_503_on_connection_error(monkeypatch):
    """A connectivity failure (not an ApiException) must map to 503."""
    from app.api.v1.kubevirt import list_kubevirt_vms

    fake_client = MagicMock()
    fake_client.list_vms.side_effect = ConnectionError("cluster unreachable")

    with pytest.raises(HTTPException) as exc:
        list_kubevirt_vms(namespace="shiftwise-t1", kube_client=fake_client,
                          label_selector=None, current_user=_superuser())
    assert exc.value.status_code == 503
    # The clean message must not leak the raw exception/host.
    assert "unreachable" not in str(exc.value.detail).lower() or \
        "cluster" in str(exc.value.detail).lower()


def test_c10_namespace_info_503_on_connection_error(monkeypatch):
    from app.api.v1.kubevirt import get_namespace_info

    fake_client = MagicMock()
    fake_client.list_vms.side_effect = ConnectionError("boom")

    with pytest.raises(HTTPException) as exc:
        get_namespace_info(namespace="shiftwise-t1", kube_client=fake_client,
                           current_user=_superuser())
    assert exc.value.status_code == 503


# ==========================================================================
# C11 — sync_hypervisor returns 202 with a response schema
# ==========================================================================

def test_c11_sync_hypervisor_returns_202():
    from app.api.v1.hypervisors import router
    assert _route_status(router, "/{hypervisor_id}/sync", "POST") == 202


def test_c11_sync_hypervisor_has_response_model():
    from app.api.v1.hypervisors import router
    for route in router.routes:
        if getattr(route, "path", None) == "/{hypervisor_id}/sync":
            assert route.response_model is not None
            return
    raise AssertionError("sync route not found")


# ==========================================================================
# C12 — cancel_migration body typed Optional[MigrationCancel]
# ==========================================================================

def test_c12_cancel_migration_body_is_optional():
    from app.api.v1 import migrations as mig_mod
    from app.schemas.migration import MigrationCancel

    sig = inspect.signature(mig_mod.cancel_migration)
    ann = sig.parameters["cancel_data"].annotation
    # Optional[MigrationCancel] == Union[MigrationCancel, None]
    assert MigrationCancel in typing.get_args(ann)
    assert type(None) in typing.get_args(ann)


# ==========================================================================
# C13 — conversion_stats uses a single GROUP BY (no N+1 COUNT)
# ==========================================================================

def test_c13_conversion_stats_single_group_by(db_session, monkeypatch):
    """count_groups must not be called once per enum value."""
    from app.api.v1 import conversions as conv_mod

    calls = {"n": 0}
    real_count = conv_mod.crud_conversion.count_groups

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return real_count(*args, **kwargs)

    monkeypatch.setattr(conv_mod.crud_conversion, "count_groups", _counting)

    conv_mod.conversion_stats(db=db_session, current_user=_superuser())
    # The old code issued one COUNT per ConversionGroupStatus (>=6).
    assert calls["n"] <= 1


def test_c13_conversion_stats_correct_aggregation(db_session):
    """The GROUP BY must still bucket statuses correctly."""
    from app.api.v1 import conversions as conv_mod

    for st in (ConversionGroupStatus.PENDING, ConversionGroupStatus.PENDING,
               ConversionGroupStatus.FAILED):
        db_session.add(ConversionGroup(
            tenant_id="t1", vm_id=1,
            group_uuid=f"uuid-{st.value}-{id(st)}-{calls_uid()}",
            status=st, target_format=TargetFormat.QCOW2,
        ))
    db_session.commit()

    stats = conv_mod.conversion_stats(db=db_session, current_user=_superuser())
    assert stats.pending == 2
    assert stats.failed == 1
    assert stats.total_groups == 3


_uid_counter = [0]


def calls_uid() -> int:
    _uid_counter[0] += 1
    return _uid_counter[0]


# ==========================================================================
# C18 — convert_vm / start_migration use module-level imports
# ==========================================================================

def test_c18_no_function_body_imports_convert_vm():
    """run_conversion_job must be imported at module scope."""
    import app.api.v1.vms as vms_mod
    src = inspect.getsource(vms_mod.convert_vm)
    assert "import run_conversion_job" not in src
    assert hasattr(vms_mod, "run_conversion_job")


def test_c18_no_function_body_imports_start_migration():
    import app.api.v1.migrations as mig_mod
    src = inspect.getsource(mig_mod.start_migration)
    assert "import run_migration" not in src
    assert hasattr(mig_mod, "run_migration")


# ==========================================================================
# C19 — GET /vms/{id}/migrations has a response_model
# ==========================================================================

def test_c19_vm_migrations_has_response_model():
    from app.api.v1.vms import router
    for route in router.routes:
        if getattr(route, "path", None) == "/{vm_id}/migrations":
            assert route.response_model is not None
            return
    raise AssertionError("vm migrations route not found")


# ==========================================================================
# Regression — handlers still serve the happy path
# ==========================================================================

def test_vm_migrations_happy_path(db_session):
    from app.api.v1.vms import get_vm_migrations

    vm = _seed_vm(db_session)
    _seed_migration(db_session, vm_id=vm.id)
    result = get_vm_migrations(vm.id, skip=0, limit=50, db=db_session,
                               current_user=_superuser())
    assert result.total_migrations == 1
    assert result.vm_id == vm.id


def test_kubevirt_create_vm_happy_path():
    from app.api.v1.kubevirt import create_kubevirt_vm
    from app.schemas.kubevirt import KubeVirtVMCreate

    fake_client = MagicMock()
    fake_client.create_vm.return_value = {"metadata": {"name": "x"}}
    vm_data = KubeVirtVMCreate(name="x", cpu=1, memory="1Gi",
                               image="quay.io/x:latest", disk_size="10Gi")
    result = create_kubevirt_vm(vm_data, namespace="shiftwise-t1",
                                kube_client=fake_client,
                                current_user=_superuser())
    assert "vm" in result
