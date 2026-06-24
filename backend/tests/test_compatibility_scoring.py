"""
Penalty-model scoring tests for the compatibility rules engine.

score = 100 − Σ(weight of each FAILED rule)
A passed rule subtracts nothing.
"""

from app.services.compatibility_rules import evaluate_all, aggregate


def _vm(**kw):
    base = {
        "cpu_cores": 4, "memory_mb": 8192, "disk_gb": 100,
        "os_type": "linux", "os_name": "Debian GNU/Linux", "os_version": "12",
        "hypervisor_type": "kvm",
    }
    base.update(kw)
    return base


def _score(vm):
    return aggregate(evaluate_all(vm))


def test_kvm_modern_linux_is_direct_100():
    r = _score(_vm(hypervisor_type="kvm"))
    assert r["score"] == 100
    assert r["grade"] == "COMPATIBLE"


def test_vmware_linux_needs_conversion_and_adaptation():
    # Penalties: disk_format vmdk (15) + guest_adaptation (20) = 35
    r = _score(_vm(hypervisor_type="vmware_workstation"))
    assert r["score"] == 65
    assert r["grade"] == "PARTIAL"


def test_physical_linux_needs_adaptation_and_driver_injection():
    # Penalties: guest_adaptation (20) + driver_injection physical Linux (15) = 35
    # physical → raw disk → PASS disk_format
    r = _score(_vm(hypervisor_type="physical"))
    assert r["score"] == 65
    assert r["grade"] == "PARTIAL"


def test_windows_on_vmware_stacks_three_interventions():
    # Penalties: disk_format vmdk (15) + guest_adaptation (20) + driver_injection windows (15) = 50
    r = _score(_vm(hypervisor_type="vmware_workstation",
                   os_type="windows", os_name="Windows Server 2019",
                   os_version="2019"))
    assert r["score"] == 50
    assert r["grade"] == "PARTIAL"


def test_proxmox_and_ovirt_are_virtio_native_100():
    assert _score(_vm(hypervisor_type="proxmox"))["score"] == 100
    assert _score(_vm(hypervisor_type="ovirt"))["score"] == 100


def test_blocker_forces_incompatible_regardless_of_score():
    # vmware_workstation is NOT a soft hypervisor → os_type "other" emits BLOCKER
    r = _score(_vm(os_type="other", os_name="Solaris 10", os_version="10",
                   hypervisor_type="vmware_workstation"))
    assert r["grade"] == "INCOMPATIBLE"
    assert r["blockers"]
