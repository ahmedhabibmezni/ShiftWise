"""
US2 — `GET /api/v1/migrations/stats/summary` RBAC gating (T033).

`by_tenant` MUST be populated only for superusers; tenant-scoped users
get an empty list. `by_hypervisor` is always present, scoped to the
caller's tenant for non-superusers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import get_migrations_stats
from app.crud import migration as crud_migration
from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import VirtualMachine


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser() -> User:
    return User(
        email="su@example.com",
        username="su",
        hashed_password="x",
        tenant_id="ops",
        is_superuser=True,
    )


def _tenant_user(tenant: str) -> User:
    return User(
        email=f"{tenant}@example.com",
        username=tenant,
        hashed_password="x",
        tenant_id=tenant,
        is_superuser=False,
    )


def _seed_hypervisor(db, name: str = "vsphere-1") -> Hypervisor:
    h = Hypervisor(
        name=name,
        type=HypervisorType.VSPHERE,
        host="10.0.0.1",
        port=443,
        tenant_id="tenant-a",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def _seed_vm(db, hypervisor_id: int, tenant: str) -> VirtualMachine:
    vm = VirtualMachine(
        name=f"vm-{tenant}",
        source_hypervisor_id=hypervisor_id,
        tenant_id=tenant,
    )
    db.add(vm)
    db.commit()
    db.refresh(vm)
    return vm


def _seed_migration(
    db, vm: VirtualMachine, tenant: str, status: MigrationStatus,
) -> Migration:
    mig = crud_migration.create_migration(
        db,
        data={
            "vm_id": vm.id,
            "strategy": MigrationStrategy.AUTO,
            "target_storage_class": "nfs-client",
        },
        tenant_id=tenant,
        target_namespace=f"shiftwise-{tenant}",
    )
    if status != MigrationStatus.PENDING:
        crud_migration.set_migration_status(db, mig.id, status)
    return mig


def test_superuser_sees_by_tenant_populated(db_session):
    h = _seed_hypervisor(db_session)
    vm_a = _seed_vm(db_session, h.id, tenant="tenant-a")
    vm_b = _seed_vm(db_session, h.id, tenant="tenant-b")
    _seed_migration(db_session, vm_a, "tenant-a", MigrationStatus.COMPLETED)
    _seed_migration(db_session, vm_b, "tenant-b", MigrationStatus.FAILED)

    stats = get_migrations_stats(db_session, _superuser())

    tenants_seen = {row.key for row in stats.by_tenant}
    assert tenants_seen == {"tenant-a", "tenant-b"}, (
        f"superuser MUST see all tenants in by_tenant, got {tenants_seen}"
    )


def test_non_superuser_gets_empty_by_tenant(db_session):
    h = _seed_hypervisor(db_session)
    vm_a = _seed_vm(db_session, h.id, tenant="tenant-a")
    vm_b = _seed_vm(db_session, h.id, tenant="tenant-b")
    _seed_migration(db_session, vm_a, "tenant-a", MigrationStatus.COMPLETED)
    _seed_migration(db_session, vm_b, "tenant-b", MigrationStatus.COMPLETED)

    stats = get_migrations_stats(db_session, _tenant_user("tenant-a"))

    assert stats.by_tenant == [], (
        "non-superuser MUST get an empty by_tenant list; got "
        f"{[row.key for row in stats.by_tenant]}"
    )


def test_by_hypervisor_always_present_for_any_role(db_session):
    h = _seed_hypervisor(db_session)
    vm = _seed_vm(db_session, h.id, tenant="tenant-a")
    _seed_migration(db_session, vm, "tenant-a", MigrationStatus.COMPLETED)

    su_stats = get_migrations_stats(db_session, _superuser())
    tenant_stats = get_migrations_stats(db_session, _tenant_user("tenant-a"))

    assert len(su_stats.by_hypervisor) >= 1
    assert len(tenant_stats.by_hypervisor) >= 1
    assert su_stats.by_hypervisor[0].label == h.name


def test_empty_dataset_returns_empty_breakdowns_for_both_roles(db_session):
    su_stats = get_migrations_stats(db_session, _superuser())
    tenant_stats = get_migrations_stats(db_session, _tenant_user("tenant-a"))

    assert su_stats.by_tenant == []
    assert su_stats.by_hypervisor == []
    assert tenant_stats.by_tenant == []
    assert tenant_stats.by_hypervisor == []
