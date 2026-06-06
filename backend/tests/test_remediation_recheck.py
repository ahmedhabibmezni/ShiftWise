"""
Audit re-check — regression tests for the verification-round fixes.

Locks in the gaps closed during the audit re-verification pass:

  C14 ConversionCreate.pull_options is threaded into the group pull_config
      (it was silently dropped before).
  C15 renaming a hypervisor onto a name already taken in the tenant raises
      ValueError (the router maps it to 409, not a raw IntegrityError → 500).
  D2  an Alembic migration adds the correctly-cased 'DISCOVERING' label to
      the hypervisorstatus enum (SQLAlchemy binds the member NAME).

(A5 — the SSRF host guard now also rejects loopback literals — is covered
in test_hypervisor_schema.py::test_loopback_hosts_rejected.)

Harness: in-memory SQLite — no live server / Postgres / Redis required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.hypervisor import Hypervisor, HypervisorStatus, HypervisorType
from app.models.virtual_machine import (
    CompatibilityStatus,
    OSType,
    VirtualMachine,
    VMStatus,
)
from app.models.conversion import SourceFormat
from app.services.converter.protocol import DiskDescriptor
from app.crud import hypervisor as crud_hv
from app.crud import conversion as crud_conv


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_hypervisor(db, *, name, tenant_id) -> Hypervisor:
    hv = Hypervisor(
        name=name, type=HypervisorType.KVM, host="10.0.0.10",
        username="root", tenant_id=tenant_id,
        status=HypervisorStatus.UNKNOWN,
    )
    db.add(hv)
    db.commit()
    db.refresh(hv)
    return hv


def _seed_vm(db, *, name, tenant_id, hypervisor_id) -> VirtualMachine:
    vm = VirtualMachine(
        name=name, cpu_cores=2, memory_mb=2048, disk_gb=20,
        os_type=OSType.LINUX, tenant_id=tenant_id,
        source_hypervisor_id=hypervisor_id,
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN,
    )
    db.add(vm)
    db.commit()
    db.refresh(vm)
    return vm


# ---------------------------------------------------------------------------
# C15 — renaming a hypervisor onto a name already taken in the tenant must
# raise ValueError (the router maps it to HTTP 409, not a raw 500).
# ---------------------------------------------------------------------------

def test_c15_rename_to_taken_name_raises_valueerror(db_session):
    _seed_hypervisor(db_session, name="hv-a", tenant_id="t1")
    hv_b = _seed_hypervisor(db_session, name="hv-b", tenant_id="t1")
    with pytest.raises(ValueError):
        crud_hv.update_hypervisor(
            db_session, hv_b.id, {"name": "hv-a"}, tenant_id="t1",
        )


def test_c15_rename_to_free_name_succeeds(db_session):
    hv = _seed_hypervisor(db_session, name="hv-old", tenant_id="t1")
    updated = crud_hv.update_hypervisor(
        db_session, hv.id, {"name": "hv-new"}, tenant_id="t1",
    )
    assert updated is not None and updated.name == "hv-new"


def test_c15_same_name_in_other_tenant_still_allowed(db_session):
    _seed_hypervisor(db_session, name="shared", tenant_id="t1")
    hv_t2 = _seed_hypervisor(db_session, name="hv-t2", tenant_id="t2")
    # Per-tenant uniqueness: tenant t2 may take a name tenant t1 holds.
    updated = crud_hv.update_hypervisor(
        db_session, hv_t2.id, {"name": "shared"}, tenant_id="t2",
    )
    assert updated is not None and updated.name == "shared"


def test_c15_unchanged_name_is_not_a_conflict(db_session):
    hv = _seed_hypervisor(db_session, name="hv-keep", tenant_id="t1")
    updated = crud_hv.update_hypervisor(
        db_session, hv.id, {"name": "hv-keep", "description": "edited"},
        tenant_id="t1",
    )
    assert updated is not None and updated.description == "edited"


# ---------------------------------------------------------------------------
# C14 — ConverterService.create_group_for_vm threads pull_options into the
# group's pull_config (the field was accepted by the API then discarded).
# ---------------------------------------------------------------------------

class _FakePuller:
    """Minimal connector puller — only list_disks is exercised here."""

    def list_disks(self, hypervisor, vm):
        return [DiskDescriptor(
            disk_index=0, source_format=SourceFormat.QCOW2,
            size_bytes=1024, locator="disk0",
        )]


def test_c14_pull_options_threaded_into_pull_config(db_session, monkeypatch):
    from app.services.converter import service as converter_service

    monkeypatch.setattr(
        converter_service, "get_puller", lambda _type: _FakePuller(),
    )
    hv = _seed_hypervisor(db_session, name="hv-c14", tenant_id="t1")
    vm = _seed_vm(db_session, name="vm-c14", tenant_id="t1", hypervisor_id=hv.id)

    group_id = converter_service.ConverterService().create_group_for_vm(
        db_session, tenant_id="t1", vm_id=vm.id,
        cold=True, pull_options={"bandwidth_limit": "50m"},
    )
    group = crud_conv.get_group(db_session, group_id)
    assert group.pull_config == {"bandwidth_limit": "50m", "cold": True}


def test_c14_explicit_cold_wins_over_pull_options(db_session, monkeypatch):
    from app.services.converter import service as converter_service

    monkeypatch.setattr(
        converter_service, "get_puller", lambda _type: _FakePuller(),
    )
    hv = _seed_hypervisor(db_session, name="hv-c14b", tenant_id="t1")
    vm = _seed_vm(db_session, name="vm-c14b", tenant_id="t1", hypervisor_id=hv.id)

    group_id = converter_service.ConverterService().create_group_for_vm(
        db_session, tenant_id="t1", vm_id=vm.id,
        cold=False, pull_options={"cold": True},
    )
    group = crud_conv.get_group(db_session, group_id)
    # The explicit `cold` argument overrides a `cold` key in the extras.
    assert group.pull_config["cold"] is False


# ---------------------------------------------------------------------------
# D2 — a migration adds the correctly-cased 'DISCOVERING' label to the
# hypervisorstatus PostgreSQL enum. SQLAlchemy's Enum binds the member NAME
# (uppercase); the earlier migration added lowercase 'discovering', which the
# ORM never produces — so a hypervisor entering discovery would have failed.
# ---------------------------------------------------------------------------

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def test_d2_a_migration_adds_uppercase_discovering_label():
    adders = []
    for path in _VERSIONS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "ADD VALUE" in text and "'DISCOVERING'" in text:
            adders.append(path.name)
    assert adders, (
        "no Alembic migration adds the uppercase 'DISCOVERING' label to the "
        "hypervisorstatus enum (audit D2)"
    )


def test_d2_enum_member_name_is_uppercase():
    # SQLAlchemy's Enum binds the member NAME, so the DB enum label must be
    # the uppercase 'DISCOVERING', matching the migration above.
    assert HypervisorStatus.DISCOVERING.name == "DISCOVERING"
