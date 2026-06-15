from app.models.hypervisor import HypervisorType
from app.models.virtual_machine import CompatibilityStatus, OSType
from app.services.discovery import _parse_lsblk_disks, _build_physical_vm_dict


def test_physical_hypervisor_type_exists():
    assert HypervisorType.PHYSICAL.value == "physical"
    # SQLAlchemy binds the member NAME (uppercase) to the PG enum label.
    assert HypervisorType.PHYSICAL.name == "PHYSICAL"


def test_parse_lsblk_disks_two_disks():
    lsblk_json = """
    {"blockdevices":[
      {"name":"sda","size":8589934592,"type":"disk","mountpoint":null,
       "children":[{"name":"sda1","size":8587837440,"type":"part","mountpoint":"/"}]},
      {"name":"sdb","size":4294967296,"type":"disk","mountpoint":null},
      {"name":"sr0","size":1073741824,"type":"rom","mountpoint":null}
    ]}
    """
    disks = _parse_lsblk_disks(lsblk_json, boot_source="/dev/sda1")
    assert [d["name"] for d in disks] == ["sda", "sdb"]
    assert disks[0]["size_bytes"] == 8589934592
    assert disks[0]["is_boot"] is True
    assert disks[1]["is_boot"] is False
    assert disks[0]["device"] == "/dev/sda"


def test_parse_lsblk_disks_boot_disk_sorted_first():
    lsblk_json = """
    {"blockdevices":[
      {"name":"sdb","size":4294967296,"type":"disk","mountpoint":null},
      {"name":"sda","size":8589934592,"type":"disk","mountpoint":null,
       "children":[{"name":"sda2","size":8587837440,"type":"part","mountpoint":"/"}]}
    ]}
    """
    disks = _parse_lsblk_disks(lsblk_json, boot_source="/dev/sda2")
    assert disks[0]["name"] == "sda"
    assert disks[0]["is_boot"] is True


def test_build_physical_vm_dict_basic():
    facts = {
        "hostname": "debian-p2v",
        "os_name": "Debian GNU/Linux",
        "os_version": "13",
        "cpu_cores": 4,
        "memory_mb": 8192,
        "uuid": "a8584d56-0dd7-0fa8-f32b-f33d4daae164",
        "ip_address": "192.168.1.14",
        "mac_address": "52:54:00:aa:bb:cc",
    }
    disks = [
        {"name": "sda", "device": "/dev/sda", "size_bytes": 8589934592, "is_boot": True},
        {"name": "sdb", "device": "/dev/sdb", "size_bytes": 4294967296, "is_boot": False},
    ]
    vm = _build_physical_vm_dict(facts, disks)

    assert vm["source_uuid"] == "a8584d560dd70fa8f32bf33d4daae164"
    assert vm["name"] == "debian-p2v"
    assert vm["cpu_cores"] == 4
    assert vm["memory_mb"] == 8192
    assert vm["os_type"] == OSType.LINUX
    assert vm["disk_gb"] == 12
    assert vm["ip_address"] == "192.168.1.14"
    assert vm["compatibility_status"] == CompatibilityStatus.UNKNOWN
    assert vm["physical_disks"] == disks


def test_build_physical_vm_dict_synthetic_uuid_fallback():
    facts = {"hostname": "no-dmi-host", "cpu_cores": 1, "memory_mb": 1024,
             "uuid": "", "os_name": "Linux", "os_version": "N/A"}
    vm = _build_physical_vm_dict(facts, [])
    assert vm["source_uuid"] == "physical-no-dmi-host"
