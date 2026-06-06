"""
Audit remediation — data-layer findings (models / schemas / crud / constants).

TDD coverage for the batch of RBAC, multi-tenancy, schema-hygiene and
service-layer findings handled by the data-layer remediation pass:

  B7  get_user accepts an optional tenant_id filter
  B8  conversions granted in ROLE_PERMISSIONS for admin/user/viewer
  B9  RoleUpdate validates the permissions map like RoleBase
  B14 get_hypervisor_by_name / get_vm_by_name accept a tenant filter
  B15 hypervisor name uniqueness is per-tenant (composite UniqueConstraint)
  B18 MigrationProgressUpdate.current_step rejects control / injection chars
  B19 the `user` role can read hypervisors
  B20 the `viewer` role can read users/roles/hypervisors
  B22 UserRead masks last_login_ip; only an admin-facing schema exposes it
  D1  conversion enums persist the .name (UPPERCASE) — DDL contract pin
  D4  UserInDB no longer carries hashed_password as a public field
  D5  HypervisorResponse masks the username credential
  D6  crud.hypervisor exposes _HYPERVISOR_PROTECTED_FIELDS and honours it
  D7  MigrationResponse exposes log_file_path + rollback_snapshot_id
  D8  tenant_id present (read-only) on VM/Hypervisor/Migration responses
  D9  HypervisorResponse exposes ssl_cert_path
  D10 *ListResponse schemas declare model_config from_attributes
  D11 MigrationResponse optional-vs-default fields are optional
  D12 conversions / kubevirt in VALID_RESOURCES
  D13 VMUpdate accepts ip_address / mac_address / hostname
  D15 UserInDB carries last_login_at / last_login_ip
  D16 model columns declare server_default
  D17 Hypervisor.mark_sync_completed persists total_vms
  D18 pure DTO schemas declare model_config
  D21 Migration.estimated_time_remaining_seconds is clamped
  E10 recompute_group_status handles EXPIRED / CANCELLED terminally
  A9  authenticate_user runs a dummy bcrypt verify on a missing user
  A20 dead reset-password / verify-email schemas removed

Harness: in-memory SQLite — no live server, Postgres or Redis required.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.role import Role, ROLE_PERMISSIONS
from app.models.virtual_machine import (
    CompatibilityStatus,
    OSType,
    VirtualMachine,
    VMStatus,
)
from app.models.conversion import (
    ConversionGroup,
    ConversionGroupStatus,
    ConversionJob,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)

from app.crud import user as crud_user
from app.crud import hypervisor as crud_hv
from app.crud import vm as crud_vm
from app.crud import conversion as crud_conv

from app.core.constants import VALID_RESOURCES
from app.core.security import get_password_hash


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_user(db, *, email, username, tenant_id) -> User:
    user = User(
        email=email,
        username=username,
        hashed_password=get_password_hash("CorrectHorse9!"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_hypervisor(db, *, name, tenant_id) -> Hypervisor:
    hv = Hypervisor(
        name=name,
        type=HypervisorType.KVM,
        host="10.0.0.10",
        username="root",
        tenant_id=tenant_id,
        status=HypervisorStatus.UNKNOWN,
    )
    db.add(hv)
    db.commit()
    db.refresh(hv)
    return hv


def _seed_vm(db, *, name, tenant_id, hypervisor_id=None) -> VirtualMachine:
    vm = VirtualMachine(
        name=name,
        cpu_cores=2,
        memory_mb=2048,
        disk_gb=20,
        os_type=OSType.LINUX,
        tenant_id=tenant_id,
        source_hypervisor_id=hypervisor_id,
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN,
    )
    db.add(vm)
    db.commit()
    db.refresh(vm)
    return vm


# --------------------------------------------------------------------------
# B7 — get_user optional tenant filter
# --------------------------------------------------------------------------

def test_b7_get_user_without_tenant_returns_user(db_session):
    user = _seed_user(db_session, email="a@x.io", username="a", tenant_id="t1")
    assert crud_user.get_user(db_session, user.id) is not None


def test_b7_get_user_matching_tenant_returns_user(db_session):
    user = _seed_user(db_session, email="a@x.io", username="a", tenant_id="t1")
    found = crud_user.get_user(db_session, user.id, tenant_id="t1")
    assert found is not None and found.id == user.id


def test_b7_get_user_wrong_tenant_returns_none(db_session):
    user = _seed_user(db_session, email="a@x.io", username="a", tenant_id="t1")
    assert crud_user.get_user(db_session, user.id, tenant_id="t2") is None


# --------------------------------------------------------------------------
# B8 — conversions granted to admin / user / viewer roles
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["admin", "user", "viewer"])
def test_b8_conversions_present_in_role(role):
    assert "conversions" in ROLE_PERMISSIONS[role]
    assert "read" in ROLE_PERMISSIONS[role]["conversions"] or \
        "*" in ROLE_PERMISSIONS[role]["conversions"]


# --------------------------------------------------------------------------
# B9 — RoleUpdate validates the permissions map
# --------------------------------------------------------------------------

def test_b9_role_update_rejects_invalid_action():
    from app.schemas.role import RoleUpdate
    with pytest.raises(ValidationError):
        RoleUpdate(permissions={"vms": ["read", "obliterate"]})


def test_b9_role_update_rejects_non_list_actions():
    from app.schemas.role import RoleUpdate
    with pytest.raises(ValidationError):
        RoleUpdate(permissions={"vms": "read"})


def test_b9_role_update_accepts_valid_permissions():
    from app.schemas.role import RoleUpdate
    upd = RoleUpdate(permissions={"vms": ["read", "create"]})
    assert upd.permissions == {"vms": ["read", "create"]}


# --------------------------------------------------------------------------
# B14 — get_hypervisor_by_name / get_vm_by_name tenant filter
# --------------------------------------------------------------------------

def test_b14_get_hypervisor_by_name_wrong_tenant_returns_none(db_session):
    _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    assert crud_hv.get_hypervisor_by_name(db_session, "hv-a", tenant_id="t2") is None


def test_b14_get_hypervisor_by_name_matching_tenant_returns_it(db_session):
    _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    found = crud_hv.get_hypervisor_by_name(db_session, "hv-a", tenant_id="t1")
    assert found is not None and found.name == "hv-a"


def test_b14_get_vm_by_name_wrong_tenant_returns_none(db_session):
    _seed_vm(db_session, name="vm-a", tenant_id="t1")
    assert crud_vm.get_vm_by_name(db_session, "vm-a", tenant_id="t2") is None


def test_b14_get_vm_by_name_matching_tenant_returns_it(db_session):
    _seed_vm(db_session, name="vm-a", tenant_id="t1")
    found = crud_vm.get_vm_by_name(db_session, "vm-a", tenant_id="t1")
    assert found is not None and found.name == "vm-a"


# --------------------------------------------------------------------------
# B15 — hypervisor name uniqueness is per-tenant
# --------------------------------------------------------------------------

def test_b15_same_name_different_tenants_allowed(db_session):
    _seed_hypervisor(db_session, name="prod-hv", tenant_id="t1")
    # the same name under another tenant must NOT collide
    _seed_hypervisor(db_session, name="prod-hv", tenant_id="t2")
    rows = db_session.query(Hypervisor).filter(Hypervisor.name == "prod-hv").all()
    assert len(rows) == 2


def test_b15_same_name_same_tenant_rejected(db_session):
    _seed_hypervisor(db_session, name="prod-hv", tenant_id="t1")
    dup = Hypervisor(
        name="prod-hv", type=HypervisorType.KVM, host="10.0.0.11",
        username="root", tenant_id="t1",
        status=HypervisorStatus.UNKNOWN,
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_b15_no_global_unique_on_name_column():
    # the bare column-level unique=True must be gone — uniqueness is composite
    assert Hypervisor.__table__.c.name.unique is not True


# --------------------------------------------------------------------------
# B18 — current_step rejects control / injection characters
# --------------------------------------------------------------------------

def test_b18_progress_update_accepts_dynamic_step():
    from app.schemas.migration import MigrationProgressUpdate
    upd = MigrationProgressUpdate(
        progress_percentage=20.0,
        current_step="Converting 3 disk(s) (40%)",
    )
    assert upd.current_step == "Converting 3 disk(s) (40%)"


def test_b18_progress_update_rejects_newline():
    from app.schemas.migration import MigrationProgressUpdate
    with pytest.raises(ValidationError):
        MigrationProgressUpdate(
            progress_percentage=20.0,
            current_step="Step\ninjected log line",
        )


def test_b18_progress_update_rejects_html_tag():
    from app.schemas.migration import MigrationProgressUpdate
    with pytest.raises(ValidationError):
        MigrationProgressUpdate(
            progress_percentage=20.0,
            current_step="<script>alert(1)</script>",
        )


# --------------------------------------------------------------------------
# B19 / B20 — RBAC matrix read-access reconciliation
# --------------------------------------------------------------------------

def test_b19_user_role_can_read_hypervisors():
    assert "read" in ROLE_PERMISSIONS["user"].get("hypervisors", [])


def test_b20_viewer_can_read_users_roles_hypervisors():
    viewer = ROLE_PERMISSIONS["viewer"]
    for resource in ("users", "roles", "hypervisors"):
        assert "read" in viewer.get(resource, []), resource


def test_b20_viewer_is_read_only():
    # a read-only role must never carry a write action
    for actions in ROLE_PERMISSIONS["viewer"].values():
        assert set(actions).issubset({"read"})


# --------------------------------------------------------------------------
# B22 / D4 / D15 — UserInDB / UserRead credential & PII exposure
# --------------------------------------------------------------------------

def test_b22_userread_does_not_expose_last_login_ip():
    from app.schemas.user import UserRead
    assert "last_login_ip" not in UserRead.model_fields


def test_b22_admin_schema_exposes_last_login_ip():
    from app.schemas import user as user_schemas
    # an admin-facing schema must still surface the audit IP
    candidates = [
        getattr(user_schemas, n) for n in dir(user_schemas)
        if isinstance(getattr(user_schemas, n), type)
        and n.startswith("User")
    ]
    assert any("last_login_ip" in c.model_fields for c in candidates), \
        "no admin-facing user schema exposes last_login_ip"


def test_d4_userindb_hashed_password_is_private():
    from app.schemas.user import UserInDB
    # hashed_password must not be a public model field anymore
    assert "hashed_password" not in UserInDB.model_fields


def test_d15_userindb_has_login_audit_fields():
    from app.schemas.user import UserInDB
    assert "last_login_at" in UserInDB.model_fields
    assert "last_login_ip" in UserInDB.model_fields


# --------------------------------------------------------------------------
# D5 / D9 — HypervisorResponse credential masking + ssl_cert_path
# --------------------------------------------------------------------------

def test_d5_hypervisor_response_masks_username():
    from app.schemas.hypervisor import HypervisorResponse
    # the plaintext username credential must not be a public field
    assert "username" not in HypervisorResponse.model_fields


def test_d9_hypervisor_response_has_ssl_cert_path():
    from app.schemas.hypervisor import HypervisorResponse
    assert "ssl_cert_path" in HypervisorResponse.model_fields


# --------------------------------------------------------------------------
# D6 — crud.hypervisor protected-field guard
# --------------------------------------------------------------------------

def test_d6_hypervisor_protected_fields_constant_exists():
    assert hasattr(crud_hv, "_HYPERVISOR_PROTECTED_FIELDS")
    protected = crud_hv._HYPERVISOR_PROTECTED_FIELDS
    assert {"id", "tenant_id", "created_at", "updated_at"}.issubset(protected)


def test_d6_update_hypervisor_ignores_protected_fields(db_session):
    hv = _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    original_id = hv.id
    crud_hv.update_hypervisor(
        db_session, hv.id,
        {"tenant_id": "attacker", "id": 9999, "description": "ok"},
    )
    db_session.refresh(hv)
    assert hv.id == original_id
    assert hv.tenant_id == "t1"          # protected — unchanged
    assert hv.description == "ok"        # non-protected — applied


# --------------------------------------------------------------------------
# D7 / D8 / D11 — MigrationResponse fields
# --------------------------------------------------------------------------

def test_d7_migration_response_has_log_and_rollback_fields():
    from app.schemas.migration import MigrationResponse
    assert "log_file_path" in MigrationResponse.model_fields
    assert "rollback_snapshot_id" in MigrationResponse.model_fields


def test_d8_tenant_id_on_response_schemas():
    from app.schemas.migration import MigrationResponse
    from app.schemas.hypervisor import HypervisorResponse
    from app.schemas.vm import VMResponse
    assert "tenant_id" in MigrationResponse.model_fields
    assert "tenant_id" in HypervisorResponse.model_fields
    assert "tenant_id" in VMResponse.model_fields


def test_d11_migration_response_optional_fields_have_defaults():
    from app.schemas.migration import MigrationResponse
    # transferred_gb / current_step_number must not be required:
    # the model column has a Python-side default, so a freshly created
    # row may surface None until the worker writes.
    for name in ("transferred_gb", "current_step_number"):
        assert not MigrationResponse.model_fields[name].is_required(), name


# --------------------------------------------------------------------------
# D10 / D18 — *ListResponse and DTO schemas declare model_config
# --------------------------------------------------------------------------

def test_d10_list_response_schemas_have_from_attributes():
    from app.schemas.hypervisor import HypervisorListResponse
    from app.schemas.vm import VMListResponse
    from app.schemas.migration import MigrationListResponse
    from app.schemas.conversion import ConversionGroupListResponse
    for schema in (
        HypervisorListResponse, VMListResponse,
        MigrationListResponse, ConversionGroupListResponse,
    ):
        assert schema.model_config.get("from_attributes") is True, schema


def test_d18_dto_schemas_have_from_attributes():
    from app.schemas.hypervisor import (
        HypervisorTestConnection,
        HypervisorTestConnectionResponse,
    )
    from app.schemas.migration import MigrationStats
    for schema in (
        HypervisorTestConnection,
        HypervisorTestConnectionResponse,
        MigrationStats,
    ):
        assert schema.model_config.get("from_attributes") is True, schema


# --------------------------------------------------------------------------
# D12 — VALID_RESOURCES completeness
# --------------------------------------------------------------------------

def test_d12_valid_resources_includes_conversions_and_kubevirt():
    assert "conversions" in VALID_RESOURCES
    assert "kubevirt" in VALID_RESOURCES


# --------------------------------------------------------------------------
# D13 — VMUpdate network fields
# --------------------------------------------------------------------------

def test_d13_vm_update_has_network_fields():
    from app.schemas.vm import VMUpdate
    for name in ("ip_address", "mac_address", "hostname"):
        assert name in VMUpdate.model_fields, name


def test_d13_vm_update_accepts_network_values():
    from app.schemas.vm import VMUpdate
    upd = VMUpdate(ip_address="10.0.0.5", mac_address="00:11:22:33:44:55",
                   hostname="web01")
    assert upd.ip_address == "10.0.0.5"
    assert upd.mac_address == "00:11:22:33:44:55"
    assert upd.hostname == "web01"


# --------------------------------------------------------------------------
# D16 — server_default on model columns
# --------------------------------------------------------------------------

def test_d16_base_timestamps_have_server_default():
    # BaseModel is an abstract mixin — assert on a concrete table that
    # inherits the created_at / updated_at columns.
    assert User.__table__.c.created_at.server_default is not None
    assert User.__table__.c.updated_at.server_default is not None


def test_d16_boolean_columns_have_server_default():
    # representative: User.is_active and Role.is_active carry a Python default;
    # a raw INSERT must not land NULL.
    assert User.__table__.c.is_active.server_default is not None
    assert Role.__table__.c.is_active.server_default is not None


# --------------------------------------------------------------------------
# D17 — mark_sync_completed persists total_vms
# --------------------------------------------------------------------------

def test_d17_mark_sync_completed_persists_total_vms(db_session):
    hv = _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    hv.mark_sync_completed(success=True, total_vms=7)
    db_session.commit()
    db_session.refresh(hv)
    assert hv.total_vms_discovered == 7


def test_d17_mark_sync_completed_failure_does_not_touch_total(db_session):
    hv = _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    hv.total_vms_discovered = 3
    db_session.commit()
    hv.mark_sync_completed(success=False, total_vms=99)
    db_session.commit()
    db_session.refresh(hv)
    assert hv.total_vms_discovered == 3


# --------------------------------------------------------------------------
# D21 — estimated_time_remaining_seconds clamp
# --------------------------------------------------------------------------

def test_d21_eta_zero_when_progress_below_one_percent():
    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
        progress_percentage=0.01,
    )
    # a sub-1% progress would yield an absurd ETA — must be clamped to 0
    assert mig.estimated_time_remaining_seconds == 0


def test_d21_eta_nonzero_for_real_progress():
    from datetime import datetime, timedelta, timezone
    mig = Migration(
        tenant_id="t1", vm_id=1, status=MigrationStatus.TRANSFERRING,
        strategy=MigrationStrategy.AUTO, target_namespace="shiftwise-t1",
        progress_percentage=50.0,
    )
    mig.started_at = datetime.now(timezone.utc) - timedelta(seconds=100)
    assert mig.estimated_time_remaining_seconds > 0


# --------------------------------------------------------------------------
# D1 — conversion enum DDL contract
# --------------------------------------------------------------------------

def test_d1_conversion_enum_persists_member_name(db_session):
    # D1 contract pin / false-positive guard.
    #
    # The audit claimed a mismatch between the Python enum (lowercase
    # .value) and the Alembic DDL (UPPERCASE members). In reality
    # SQLAlchemy's SQLEnum binds the member NAME, not the value — so the
    # column stores 'IN_PROGRESS', exactly what the conversion DDL
    # (c7d2e8f4a1b3) declares. This is the same name-binding posture as
    # MigrationStatus / VMStatus / HypervisorStatus, all in production.
    #
    # This test pins that contract so a future rename cannot drift the
    # stored representation away from the DDL enum members.
    from sqlalchemy import text

    group = ConversionGroup(
        tenant_id="t1", vm_id=1,
        group_uuid="11111111-2222-3333-4444-555555555555",
        status=ConversionGroupStatus.IN_PROGRESS,
        target_format=TargetFormat.QCOW2,
    )
    db_session.add(group)
    db_session.commit()
    # raw textual query — bypasses the SQLEnum type decoder
    raw = db_session.execute(
        text("SELECT status, target_format FROM conversion_groups")
    ).fetchone()
    # stored representation is the .name, UPPERCASE — matches the DDL
    assert raw[0] == "IN_PROGRESS"
    assert raw[1] == "QCOW2"
    # the declared enum members are the UPPERCASE names, never the values
    declared = ConversionGroup.__table__.c.status.type.enums
    assert "IN_PROGRESS" in declared
    assert "in_progress" not in declared


# --------------------------------------------------------------------------
# E10 — recompute_group_status handles EXPIRED / CANCELLED terminally
# --------------------------------------------------------------------------

def _seed_group_with_job(db, job_status: ConversionStatus) -> ConversionGroup:
    group = ConversionGroup(
        tenant_id="t1", vm_id=1,
        group_uuid=f"group-{job_status.value}-uuid-padding-000000",
        status=ConversionGroupStatus.IN_PROGRESS,
        target_format=TargetFormat.QCOW2,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    job = ConversionJob(
        tenant_id="t1", group_id=group.id, vm_id=1, disk_index=0,
        source_format=SourceFormat.VMDK, target_format=TargetFormat.QCOW2,
        tool=ConversionTool.QEMU_IMG, status=job_status,
    )
    db.add(job)
    db.commit()
    db.refresh(group)
    return group


def test_e10_all_expired_jobs_make_group_terminal(db_session):
    group = _seed_group_with_job(db_session, ConversionStatus.EXPIRED)
    crud_conv.recompute_group_status(db_session, group.id)
    db_session.refresh(group)
    # an EXPIRED-only group must NOT stay IN_PROGRESS forever
    assert group.status != ConversionGroupStatus.IN_PROGRESS


def test_e10_expired_plus_ready_is_not_in_progress(db_session):
    group = _seed_group_with_job(db_session, ConversionStatus.READY)
    expired = ConversionJob(
        tenant_id="t1", group_id=group.id, vm_id=1, disk_index=1,
        source_format=SourceFormat.VMDK, target_format=TargetFormat.QCOW2,
        tool=ConversionTool.QEMU_IMG, status=ConversionStatus.EXPIRED,
    )
    db_session.add(expired)
    db_session.commit()
    crud_conv.recompute_group_status(db_session, group.id)
    db_session.refresh(group)
    assert group.status != ConversionGroupStatus.IN_PROGRESS


def test_e10_cancelled_only_group_is_terminal(db_session):
    group = _seed_group_with_job(db_session, ConversionStatus.CANCELLED)
    crud_conv.recompute_group_status(db_session, group.id)
    db_session.refresh(group)
    assert group.status == ConversionGroupStatus.CANCELLED


# --------------------------------------------------------------------------
# A9 — dummy bcrypt verify on a missing user (timing-oracle defence)
# --------------------------------------------------------------------------

def test_a9_authenticate_missing_user_returns_none(db_session):
    assert crud_user.authenticate_user(
        db_session, "ghost@nowhere.io", "whatever"
    ) is None


def test_a9_authenticate_missing_user_is_not_instant(db_session):
    # the dummy verify must spend comparable time to a real bcrypt check,
    # so a missing account is not distinguishable by response latency.
    start = time.perf_counter()
    crud_user.authenticate_user(db_session, "ghost@nowhere.io", "whatever")
    elapsed = time.perf_counter() - start
    # a real bcrypt verify is milliseconds, not microseconds
    assert elapsed > 0.005


def test_a9_authenticate_valid_credentials_succeed(db_session):
    _seed_user(db_session, email="real@x.io", username="real", tenant_id="t1")
    user = crud_user.authenticate_user(db_session, "real@x.io", "CorrectHorse9!")
    assert user is not None and user.email == "real@x.io"


def test_a9_authenticate_wrong_password_returns_none(db_session):
    _seed_user(db_session, email="real@x.io", username="real", tenant_id="t1")
    assert crud_user.authenticate_user(
        db_session, "real@x.io", "WrongPassword!"
    ) is None


# --------------------------------------------------------------------------
# A20 — dead reset-password / verify-email schemas removed
# --------------------------------------------------------------------------

def test_a20_dead_auth_schemas_removed():
    import app.schemas.auth as auth_schemas
    for dead in ("ResetPasswordRequest", "ResetPasswordConfirm",
                 "VerifyEmailRequest"):
        assert not hasattr(auth_schemas, dead), dead
