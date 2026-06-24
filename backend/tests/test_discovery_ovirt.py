"""Tests for the SDK-free oVirt REST discovery path (discovery.py)."""

from app.models.virtual_machine import OSType
from app.services.discovery import (
    DiscoveryService,
    _ovirt_rest_first_ipv4,
    _parse_ovirt_vm_rest,
)


# Real-shape VM JSON captured from oVirt 4.5 (cpu topology values are strings,
# memory is a number, bios.type q35_ovmf => UEFI).
_VM_JSON = {
    "id": "85fd0955-f674-4858-b1eb-c26e569f4fa7",
    "name": "shiftwise-testvm",
    "memory": 536870912,
    "cpu": {"topology": {"cores": "1", "sockets": "1", "threads": "1"}},
    "status": "up",
    "os": {"type": "other_linux"},
    "bios": {"type": "q35_ovmf"},
    "fqdn": "testvm.local",
}


class _HV:
    def __init__(self, **kw):
        self.host = kw.get("host", "manager.engine.local")
        self.port = kw.get("port")
        self.username = kw.get("username", "admin@internal")
        self.password_plain = kw.get("password_plain", "root")
        self.verify_ssl = kw.get("verify_ssl", False)
        self.ssl_cert_path = kw.get("ssl_cert_path")
        self.connection_config = kw.get("connection_config", {})


class _FakeRest:
    def __init__(self, vms, attachments=None, disks=None, devices=None):
        self._vms = vms
        self._attachments = attachments or []
        self._disks = disks or {}
        self._devices = devices or []
        self.closed = False

    def list_vms(self):
        return self._vms

    def list_disk_attachments(self, vm_id):
        return self._attachments

    def get_disk(self, disk_id):
        return self._disks[disk_id]

    def list_reported_devices(self, vm_id):
        return self._devices

    def close(self):
        self.closed = True


class TestParseOvirtVmRest:
    def test_full_shape(self):
        d = _parse_ovirt_vm_rest(_VM_JSON, disk_gb=1)
        assert d["source_uuid"] == "85fd0955f6744858b1ebc26e569f4fa7"
        assert d["name"] == "shiftwise-testvm"
        assert d["cpu_cores"] == 1
        assert d["memory_mb"] == 512
        assert d["os_type"] == OSType.LINUX
        assert d["firmware"] == "efi"          # q35_ovmf
        assert d["power_state"] == "running"   # up
        assert d["disk_gb"] == 1
        assert d["hostname"] == "testvm.local"

    def test_multicore_string_topology(self):
        vm = {**_VM_JSON, "cpu": {"topology": {"cores": "2", "sockets": "2", "threads": "1"}}}
        assert _parse_ovirt_vm_rest(vm, 0)["cpu_cores"] == 4

    def test_first_ipv4_nested_and_skips_loopback(self):
        devices = [{
            "mac": {"address": "56:6f:32:1d:00:00"},
            "ips": {"ip": [
                {"address": "127.0.0.1", "version": "v4"},
                {"address": "172.16.100.200", "version": "v4"},
            ]},
        }]
        ip, mac = _ovirt_rest_first_ipv4(devices)
        assert ip == "172.16.100.200"
        assert mac == "56:6f:32:1d:00:00"


class TestDiscoverOvirtRest:
    def test_end_to_end_single_vm(self, monkeypatch):
        fake = _FakeRest(
            vms=[_VM_JSON],
            attachments=[{"disk": {"id": "d99627a7"}}],
            disks={"d99627a7": {"provisioned_size": 117440512}},
        )
        import app.services.ovirt_rest as ovr
        monkeypatch.setattr(ovr, "OvirtRestClient", lambda hv, **kw: fake)

        svc = DiscoveryService(db=None)
        vms = svc._discover_ovirt_rest(_HV())
        assert len(vms) == 1
        assert vms[0]["name"] == "shiftwise-testvm"
        assert vms[0]["firmware"] == "efi"
        assert vms[0]["disk_gb"] == 1  # 112 MiB rounds to 0 -> clamped to 1
        assert fake.closed is True

    def test_empty_engine_returns_empty(self, monkeypatch):
        fake = _FakeRest(vms=[])
        import app.services.ovirt_rest as ovr
        monkeypatch.setattr(ovr, "OvirtRestClient", lambda hv, **kw: fake)
        assert DiscoveryService(db=None)._discover_ovirt_rest(_HV()) == []
