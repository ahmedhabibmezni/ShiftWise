"""
Tests pour l'endpoint /api/v1/migrations/stats/summary avec les breakdowns
par tenant et par hyperviseur.

Valide :
- Un superuser voit `by_tenant` couvrant tous les tenants.
- Un utilisateur normal voit `by_tenant` vide (sa propre vue est déjà
  reflétée dans les compteurs globaux).
- `by_hypervisor` est groupé par hyperviseur source et filtré par tenant
  pour un non-superuser.
- Les comptes par hyperviseur séparent correctement completed / failed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.migrations import get_migrations_stats
from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.user import User
from app.models.virtual_machine import (
    CompatibilityStatus,
    OSType,
    VirtualMachine,
    VMStatus,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _superuser() -> User:
    return User(
        email="su@example.com", username="su", hashed_password="x",
        tenant_id="su-tenant", is_superuser=True,
    )


def _tenant_user(tenant: str) -> User:
    return User(
        email=f"{tenant}@example.com", username=tenant, hashed_password="x",
        tenant_id=tenant, is_superuser=False,
    )


def _seed_hypervisor(
    db, name: str, htype: HypervisorType, tenant: str = "shared",
) -> Hypervisor:
    h = Hypervisor(
        name=name, tenant_id=tenant, type=htype, host="10.0.0.1", username="root",
        status=HypervisorStatus.ACTIVE,
    )
    db.add(h)
    db.commit()
    return h


def _seed_vm(db, name: str, tenant: str, hypervisor: Hypervisor) -> VirtualMachine:
    vm = VirtualMachine(
        name=name, tenant_id=tenant, source_hypervisor_id=hypervisor.id,
        source_uuid=f"uuid-{name}", cpu_cores=2, memory_mb=2048, disk_gb=10,
        os_type=OSType.LINUX, status=VMStatus.COMPATIBLE,
        compatibility_status=CompatibilityStatus.COMPATIBLE,
    )
    db.add(vm)
    db.commit()
    return vm


def _seed_migration(
    db, tenant: str, vm_id: int, status: MigrationStatus,
) -> Migration:
    mig = Migration(
        tenant_id=tenant, vm_id=vm_id, status=status,
        strategy=MigrationStrategy.AUTO,
        target_namespace=f"shiftwise-{tenant}",
    )
    db.add(mig)
    db.commit()
    return mig


def test_superuser_sees_per_tenant_breakdown_across_all_tenants(db_session):
    hyp = _seed_hypervisor(db_session, "kvm-1", HypervisorType.KVM)
    vm_a = _seed_vm(db_session, "vm-a", "tenant-a", hyp)
    vm_b = _seed_vm(db_session, "vm-b", "tenant-b", hyp)

    _seed_migration(db_session, "tenant-a", vm_a.id, MigrationStatus.COMPLETED)
    _seed_migration(db_session, "tenant-a", vm_a.id, MigrationStatus.FAILED)
    _seed_migration(db_session, "tenant-b", vm_b.id, MigrationStatus.COMPLETED)

    stats = get_migrations_stats(db_session, _superuser())

    by_tenant = {row.key: row for row in stats.by_tenant}
    assert set(by_tenant) == {"tenant-a", "tenant-b"}
    assert by_tenant["tenant-a"].total == 2
    assert by_tenant["tenant-a"].completed == 1
    assert by_tenant["tenant-a"].failed == 1
    assert by_tenant["tenant-b"].total == 1
    assert by_tenant["tenant-b"].completed == 1


def test_non_superuser_does_not_receive_per_tenant_breakdown(db_session):
    """A regular user already sees their own tenant in the top-level counters.

    Sending `by_tenant` for non-superusers would either leak other tenants'
    aggregates or duplicate the top-level numbers — both undesirable.
    """
    hyp = _seed_hypervisor(db_session, "kvm-1", HypervisorType.KVM)
    vm = _seed_vm(db_session, "vm-a", "tenant-a", hyp)
    _seed_migration(db_session, "tenant-a", vm.id, MigrationStatus.COMPLETED)

    stats = get_migrations_stats(db_session, _tenant_user("tenant-a"))

    assert stats.by_tenant == []


def test_per_hypervisor_breakdown_separates_completed_and_failed(db_session):
    kvm = _seed_hypervisor(db_session, "kvm-1", HypervisorType.KVM)
    vmware = _seed_hypervisor(db_session, "vmware-1", HypervisorType.VMWARE_WORKSTATION)

    vm_kvm_a = _seed_vm(db_session, "vm-kvm-a", "t1", kvm)
    vm_kvm_b = _seed_vm(db_session, "vm-kvm-b", "t1", kvm)
    vm_vmware = _seed_vm(db_session, "vm-vmware", "t1", vmware)

    _seed_migration(db_session, "t1", vm_kvm_a.id, MigrationStatus.COMPLETED)
    _seed_migration(db_session, "t1", vm_kvm_b.id, MigrationStatus.FAILED)
    _seed_migration(db_session, "t1", vm_vmware.id, MigrationStatus.COMPLETED)

    stats = get_migrations_stats(db_session, _tenant_user("t1"))

    by_hyp = {row.label: row for row in stats.by_hypervisor}
    assert set(by_hyp) == {"kvm-1", "vmware-1"}
    assert by_hyp["kvm-1"].total == 2
    assert by_hyp["kvm-1"].completed == 1
    assert by_hyp["kvm-1"].failed == 1
    assert by_hyp["vmware-1"].total == 1
    assert by_hyp["vmware-1"].completed == 1


def test_per_hypervisor_breakdown_isolates_tenants_for_non_superuser(db_session):
    hyp = _seed_hypervisor(db_session, "shared-kvm", HypervisorType.KVM)
    vm_a = _seed_vm(db_session, "vm-a", "tenant-a", hyp)
    vm_b = _seed_vm(db_session, "vm-b", "tenant-b", hyp)

    _seed_migration(db_session, "tenant-a", vm_a.id, MigrationStatus.COMPLETED)
    _seed_migration(db_session, "tenant-b", vm_b.id, MigrationStatus.COMPLETED)
    _seed_migration(db_session, "tenant-b", vm_b.id, MigrationStatus.FAILED)

    # tenant-a user must NOT see tenant-b's two extra migrations counted on
    # the same hypervisor row.
    stats = get_migrations_stats(db_session, _tenant_user("tenant-a"))
    by_hyp = {row.label: row for row in stats.by_hypervisor}
    assert by_hyp["shared-kvm"].total == 1
    assert by_hyp["shared-kvm"].completed == 1
    assert by_hyp["shared-kvm"].failed == 0


def test_empty_dataset_returns_empty_breakdowns(db_session):
    stats = get_migrations_stats(db_session, _superuser())
    assert stats.total_migrations == 0
    assert stats.by_tenant == []
    assert stats.by_hypervisor == []
