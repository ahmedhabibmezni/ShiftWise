import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.hypervisor import HypervisorType, HypervisorStatus
from app.models.virtual_machine import CompatibilityStatus, OSType
from app.services.discovery import _parse_lsblk_disks, _build_physical_vm_dict, DiscoveryService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


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


def test_collect_physical_facts_single_vm():
    responses = {
        "hostname": ("debian-p2v", "", 0),
        "os-release": ('NAME="Debian GNU/Linux"\nVERSION_ID="13"', "", 0),
        "nproc": ("4", "", 0),
        "MemTotal": ("MemTotal:        8192000 kB", "", 0),
        "product_uuid": ("a8584d56-0dd7-0fa8-f32b-f33d4daae164", "", 0),
        "findmnt": ("/dev/sda1", "", 0),
        "lsblk": ('{"blockdevices":[{"name":"sda","size":8589934592,"type":"disk",'
                  '"mountpoint":null,"children":[{"name":"sda1","size":8587837440,'
                  '"type":"part","mountpoint":"/"}]},'
                  '{"name":"sdb","size":4294967296,"type":"disk","mountpoint":null}]}',
                  "", 0),
        "ip -j": ('[{"ifname":"ens33","addr_info":[{"local":"192.168.1.14"}],'
                  '"address":"52:54:00:aa:bb:cc"}]', "", 0),
    }

    def fake_run(cmd: str):
        for key, val in responses.items():
            if key in cmd:
                return val
        return ("", "", 0)

    svc = DiscoveryService.__new__(DiscoveryService)
    vms = svc._collect_physical_facts(fake_run)
    assert len(vms) == 1
    vm = vms[0]
    assert vm["name"] == "debian-p2v"
    assert vm["cpu_cores"] == 4
    assert vm["memory_mb"] == 8000
    assert vm["os_name"] == "Debian GNU/Linux"
    assert vm["source_uuid"] == "a8584d560dd70fa8f32bf33d4daae164"
    assert vm["ip_address"] == "192.168.1.14"
    assert len(vm["physical_disks"]) == 2


# ---------------------------------------------------------------------------
# DB-level tests: physical_disks persisted into custom_metadata
# ---------------------------------------------------------------------------

def test_save_physical_vm_persists_disk_plan(db_session):
    from app.models.hypervisor import Hypervisor
    from app.models.virtual_machine import VirtualMachine

    hv = Hypervisor(
        name="bare-metal-1", type=HypervisorType.PHYSICAL,
        host="192.168.1.14", username="root", tenant_id="t1",
        status=HypervisorStatus.ACTIVE,
    )
    db_session.add(hv)
    db_session.commit()

    disks = [
        {"name": "sda", "device": "/dev/sda", "size_bytes": 8589934592, "is_boot": True},
        {"name": "sdb", "device": "/dev/sdb", "size_bytes": 4294967296, "is_boot": False},
    ]
    vm_dict = {
        "source_uuid": "a8584d560dd70fa8f32bf33d4daae164",
        "source_name": "debian-p2v",
        "name": "debian-p2v",
        "cpu_cores": 4,
        "memory_mb": 8000,
        "disk_gb": 12,
        "os_type": OSType.LINUX,
        "os_version": "13",
        "os_name": "Debian GNU/Linux",
        "ip_address": "192.168.1.14",
        "mac_address": "52:54:00:aa:bb:cc",
        "hostname": "debian-p2v",
        "power_state": "running",
        "compatibility_status": CompatibilityStatus.UNKNOWN,
        "physical_disks": disks,
    }

    svc = DiscoveryService(db_session)
    svc._save_discovered_vms(hv, [vm_dict])

    vm = db_session.query(VirtualMachine).filter_by(
        source_uuid="a8584d560dd70fa8f32bf33d4daae164"
    ).one()
    assert vm.custom_metadata is not None
    assert vm.custom_metadata["physical_disks"] == disks


def test_rediscover_physical_vm_updates_disk_plan(db_session):
    """Rediscovery (UPDATE path) must also refresh physical_disks in custom_metadata."""
    from app.models.hypervisor import Hypervisor
    from app.models.virtual_machine import VirtualMachine

    hv = Hypervisor(
        name="bare-metal-2", type=HypervisorType.PHYSICAL,
        host="192.168.1.15", username="root", tenant_id="t2",
        status=HypervisorStatus.ACTIVE,
    )
    db_session.add(hv)
    db_session.commit()

    initial_disks = [
        {"name": "sda", "device": "/dev/sda", "size_bytes": 8589934592, "is_boot": True},
    ]
    vm_dict = {
        "source_uuid": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "source_name": "ubuntu-p2v",
        "name": "ubuntu-p2v",
        "cpu_cores": 2,
        "memory_mb": 4096,
        "disk_gb": 8,
        "os_type": OSType.LINUX,
        "os_version": "22.04",
        "os_name": "Ubuntu",
        "ip_address": "192.168.1.15",
        "power_state": "running",
        "compatibility_status": CompatibilityStatus.UNKNOWN,
        "physical_disks": initial_disks,
    }

    svc = DiscoveryService(db_session)
    svc._save_discovered_vms(hv, [vm_dict])

    # Second discovery with an updated disk list (a new disk was added)
    updated_disks = [
        {"name": "sda", "device": "/dev/sda", "size_bytes": 8589934592, "is_boot": True},
        {"name": "sdc", "device": "/dev/sdc", "size_bytes": 2147483648, "is_boot": False},
    ]
    vm_dict["physical_disks"] = updated_disks
    svc._save_discovered_vms(hv, [vm_dict])

    vm = db_session.query(VirtualMachine).filter_by(
        source_uuid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    ).one()
    assert vm.custom_metadata["physical_disks"] == updated_disks
