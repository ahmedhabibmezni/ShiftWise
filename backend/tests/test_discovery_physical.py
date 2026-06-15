from app.models.hypervisor import HypervisorType
from app.services.discovery import _parse_lsblk_disks


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
