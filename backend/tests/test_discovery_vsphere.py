"""Unit tests for the real vSphere/ESXi discovery path.

No live ESXi is available in CI, so the network boundary (`_vsphere_fetch_vms`)
is monkeypatched. The mapping helpers are pure and getattr-based, so they are
exercised directly with `SimpleNamespace` stand-ins for pyVmomi managed objects.
"""

from types import SimpleNamespace

import pytest

from app.models.hypervisor import HypervisorStatus, HypervisorType
from app.models.virtual_machine import OSType
from app.services import discovery
from app.services.discovery import DiscoveryError, DiscoveryService


# --------------------------------------------------------------------------- #
# Fakes (mirror test_remediation_services._FakeHypervisor / _FakeDb)
# --------------------------------------------------------------------------- #


class _FakeHypervisor:
    def __init__(self, hv_type):
        self.id = 1
        self.name = "esxi-lab"
        self.type = hv_type
        self.tenant_id = "t1"
        self.status = HypervisorStatus.ACTIVE
        self.host = "192.168.168.48"
        self.port = 443
        self.username = "root"
        self.verify_ssl = False
        self.connection_config = {}
        self.last_sync_at = None
        self.total_vms_discovered = 0

    @property
    def password_plain(self):
        return "Securepass123!"

    def update_status(self, status, error_message=None):
        self.status = status

    def mark_sync_completed(self, success=True, total_vms=None):
        pass


def _running_vm():
    """A powered-on Ubuntu VM with VMware Tools reporting net info."""
    disk = SimpleNamespace(capacityInKB=16 * 1024 * 1024)  # 16 GiB
    nic = SimpleNamespace(macAddress="00:50:56:aa:bb:cc")
    return SimpleNamespace(
        name="ubuntu",
        config=SimpleNamespace(
            instanceUuid="52af-1234-5678-90ab-cdef12345678".replace("-", "-"),
            uuid="564d1111-2222-3333-4444-555566667777",
            guestFullName="Ubuntu Linux (64-bit)",
            guestId="ubuntu64Guest",
            hardware=SimpleNamespace(numCPU=2, memoryMB=4096, device=[disk]),
        ),
        guest=SimpleNamespace(
            guestFullName="Ubuntu Linux (64-bit)",
            guestId="ubuntu64Guest",
            ipAddress="192.168.168.90",
            hostName="ubuntu",
            net=[nic],
        ),
        runtime=SimpleNamespace(powerState="poweredOn"),
    )


def _stopped_vm():
    """A powered-off VM: no guest agent → no IP/MAC/hostname."""
    disk = SimpleNamespace(capacityInBytes=8 * 1024 ** 3)  # 8 GiB
    return SimpleNamespace(
        name="win2019",
        config=SimpleNamespace(
            instanceUuid="ABCD-EF01",
            uuid=None,
            guestFullName="Microsoft Windows Server 2019 (64-bit)",
            guestId="windows2019srv_64Guest",
            hardware=SimpleNamespace(numCPU=4, memoryMB=8192, device=[disk]),
        ),
        guest=SimpleNamespace(
            guestFullName=None, guestId=None,
            ipAddress=None, hostName=None, net=[],
        ),
        runtime=SimpleNamespace(powerState="poweredOff"),
    )


# --------------------------------------------------------------------------- #
# _vsphere_os_type
# --------------------------------------------------------------------------- #


class TestVsphereOsType:
    def test_ubuntu_is_linux(self):
        assert discovery._vsphere_os_type("Ubuntu Linux (64-bit)", "ubuntu64Guest") == OSType.LINUX

    def test_windows_is_windows(self):
        assert discovery._vsphere_os_type(
            "Microsoft Windows Server 2019 (64-bit)", "windows2019srv_64Guest"
        ) == OSType.WINDOWS

    def test_freebsd_is_other_not_windows(self):
        # "darwin"/"freebsd" must be classified before the "win" substring check.
        assert discovery._vsphere_os_type("FreeBSD (64-bit)", "freebsd64Guest") == OSType.OTHER

    def test_empty_is_unknown(self):
        assert discovery._vsphere_os_type("", "") == OSType.UNKNOWN

    def test_falls_back_to_guest_id(self):
        assert discovery._vsphere_os_type("", "centos8_64Guest") == OSType.LINUX


# --------------------------------------------------------------------------- #
# _vsphere_normalise_uuid
# --------------------------------------------------------------------------- #


class TestVsphereNormaliseUuid:
    def test_strips_dashes_and_lowercases(self):
        assert discovery._vsphere_normalise_uuid(
            "564D1111-2222-3333-4444-555566667777"
        ) == "564d111122223333444455556666777" + "7"

    def test_none_is_empty(self):
        assert discovery._vsphere_normalise_uuid(None) == ""


# --------------------------------------------------------------------------- #
# _vsphere_vm_to_dict
# --------------------------------------------------------------------------- #


class TestVsphereVmToDict:
    def test_running_vm_full_fields(self):
        d = discovery._vsphere_vm_to_dict(_running_vm())
        assert d["name"] == "ubuntu"
        assert d["source_name"] == "ubuntu"
        # instanceUuid preferred, normalized (no dashes, lowercase)
        assert d["source_uuid"] and "-" not in d["source_uuid"]
        assert d["source_uuid"] == d["source_uuid"].lower()
        assert d["cpu_cores"] == 2
        assert d["memory_mb"] == 4096
        assert d["disk_gb"] == 16
        assert d["os_type"] == OSType.LINUX
        assert d["ip_address"] == "192.168.168.90"
        assert d["mac_address"] == "00:50:56:aa:bb:cc"
        assert d["hostname"] == "ubuntu"
        assert d["power_state"] == "running"

    def test_uuid_falls_back_to_bios_uuid(self):
        vm = _running_vm()
        vm.config.instanceUuid = None
        d = discovery._vsphere_vm_to_dict(vm)
        assert d["source_uuid"] == "564d1111222233334444555566667777"

    def test_stopped_vm_no_guest_net(self):
        d = discovery._vsphere_vm_to_dict(_stopped_vm())
        assert d["os_type"] == OSType.WINDOWS
        assert d["disk_gb"] == 8
        assert d["ip_address"] is None
        assert d["mac_address"] is None
        assert d["power_state"] == "stopped"
        # Required keys must always be present for _save_discovered_vms.
        for key in ("name", "source_uuid", "source_name"):
            assert key in d and d[key]


# --------------------------------------------------------------------------- #
# _discover_vsphere (network boundary monkeypatched)
# --------------------------------------------------------------------------- #


class TestDiscoverVsphere:
    def test_returns_fetched_dicts(self, monkeypatch):
        # _vsphere_fetch_vms maps while the SOAP session is open and returns
        # plain dicts; _discover_vsphere just surfaces them.
        fetched = [
            discovery._vsphere_vm_to_dict(_running_vm()),
            discovery._vsphere_vm_to_dict(_stopped_vm()),
        ]
        monkeypatch.setattr(discovery, "_vsphere_fetch_vms", lambda hv: fetched)
        svc = DiscoveryService(db=None)
        hv = _FakeHypervisor(HypervisorType.VSPHERE)
        result = svc._discover_vsphere(hv)
        assert [r["name"] for r in result] == ["ubuntu", "win2019"]
        assert all("source_uuid" in r for r in result)

    def test_no_more_hardcoded_simulation_vms(self):
        import inspect
        src = inspect.getsource(DiscoveryService._discover_vsphere)
        # The stub's fake inventory must be gone.
        assert "web-server-prod" not in src
        assert "vm-001-vsphere" not in src
        assert "SIMULATION" not in src

    def test_missing_pyvmomi_raises_discovery_error(self, monkeypatch):
        def _no_lib(hv):
            raise ImportError("No module named 'pyVim'")
        monkeypatch.setattr(discovery, "_vsphere_fetch_vms", _no_lib)
        svc = DiscoveryService(db=None)
        hv = _FakeHypervisor(HypervisorType.VSPHERE)
        with pytest.raises(DiscoveryError):
            svc._discover_vsphere(hv)
