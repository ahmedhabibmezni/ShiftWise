"""
Tests de découverte Hyper-V — trois scénarios INSERT / UPDATE / ARCHIVE.

Skipped on non-Windows platforms (PowerShell / Hyper-V not available).
Requires a running server at http://localhost:8000 and hypervisor id=35
with auth_mode=local pointing at the local machine.
"""

import platform
import time

import pytest
import requests

BASE_URL = "http://localhost:8000"
HYPERVISOR_ID = 35
MIGRATOR_UUID = "95b48096df704999978eb374f8ddaeb7"
FAKE_UUID = "aaaa0000000000000000000000000001"

pytestmark = pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Hyper-V discovery requires Windows",
)


@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": "superuser@nextstep-it.com", "password": "SecurePass123!"},
        timeout=10,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db():
    from app.core.database import SessionLocal
    session = SessionLocal()
    yield session
    session.close()


def _sync(headers) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/v1/hypervisors/{HYPERVISOR_ID}/sync",
        headers=headers,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["statistics"]


def _get_migrator(db):
    from app.models.virtual_machine import VirtualMachine
    return (
        db.query(VirtualMachine)
        .filter(
            VirtualMachine.source_hypervisor_id == HYPERVISOR_ID,
            VirtualMachine.source_uuid == MIGRATOR_UUID,
        )
        .first()
    )


def _delete_migrator(db):
    from app.models.virtual_machine import VirtualMachine
    db.query(VirtualMachine).filter(
        VirtualMachine.source_hypervisor_id == HYPERVISOR_ID,
        VirtualMachine.source_uuid == MIGRATOR_UUID,
    ).delete(synchronize_session=False)
    db.commit()


def _delete_fake(db):
    from app.models.virtual_machine import VirtualMachine
    db.query(VirtualMachine).filter(
        VirtualMachine.source_uuid == FAKE_UUID,
    ).delete(synchronize_session=False)
    db.commit()


def test_insert_scenario(auth_headers, db):
    """Scénario INSERT — VM absente de la DB avant sync → créée."""
    _delete_migrator(db)
    db.expire_all()

    stats = _sync(auth_headers)

    assert stats["total_discovered"] >= 1
    assert stats["new_vms"] >= 1
    assert stats["errors"] == 0

    vm = _get_migrator(db)
    db.expire_all()
    assert vm is not None, "migrator VM should have been inserted"
    assert vm.source_uuid == MIGRATOR_UUID
    assert vm.status.value == "discovered"

    from app.models.virtual_machine import OSType, CompatibilityStatus
    assert vm.os_type == OSType.UNKNOWN, f"expected UNKNOWN, got {vm.os_type}"
    assert vm.os_version == "N/A"
    assert vm.os_name == "N/A"
    assert vm.compatibility_status == CompatibilityStatus.UNKNOWN


def test_update_scenario(auth_headers, db):
    """Scénario UPDATE — seconde sync → last_seen_at avancé, pas de doublon."""
    vm_before = _get_migrator(db)
    assert vm_before is not None, "run test_insert_scenario first"
    ts_before = vm_before.last_seen_at
    db.expire_all()

    time.sleep(1)  # ensure clock advances
    stats = _sync(auth_headers)

    assert stats["new_vms"] == 0
    assert stats["updated_vms"] >= 1
    assert stats["errors"] == 0

    db.expire_all()
    vm_after = _get_migrator(db)
    assert vm_after is not None
    assert vm_after.last_seen_at > ts_before, "last_seen_at must advance on re-sync"

    # Only one row for this UUID
    from app.models.virtual_machine import VirtualMachine
    count = (
        db.query(VirtualMachine)
        .filter(VirtualMachine.source_uuid == MIGRATOR_UUID)
        .count()
    )
    assert count == 1, f"expected 1 row, got {count}"


def test_archive_scenario(auth_headers, db):
    """Scénario ARCHIVE — fausse VM injectée → archivée après sync, migrator intact."""
    from app.models.virtual_machine import VirtualMachine, VMStatus

    _delete_fake(db)

    fake = VirtualMachine(
        name="fake-hyperv-ghost",
        tenant_id="nextstep-it",
        source_hypervisor_id=HYPERVISOR_ID,
        source_uuid=FAKE_UUID,
        source_name="fake-hyperv-ghost",
        cpu_cores=1,
        memory_mb=512,
        disk_gb=5,
        status=VMStatus.DISCOVERED,
    )
    db.add(fake)
    db.commit()
    fake_id = fake.id

    stats = _sync(auth_headers)

    assert stats["archived_vms"] >= 1
    assert stats["errors"] == 0

    db.expire_all()
    ghost = db.query(VirtualMachine).filter(VirtualMachine.id == fake_id).first()
    assert ghost is not None
    assert ghost.status == VMStatus.ARCHIVED, f"expected ARCHIVED, got {ghost.status}"

    migrator = _get_migrator(db)
    assert migrator is not None
    assert migrator.status.value == "discovered", "migrator must not be archived"

    _delete_fake(db)
