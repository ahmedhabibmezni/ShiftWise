"""Unit tests for the Hyper-V discovery output parser.

Covers the two data-quality fixes:
  - memory is sourced from the VM's configured Startup RAM (stable across
    power state and Dynamic Memory), not the live MemoryAssigned value;
  - guest OS is classified from the KVP-reported OSName, falling back to
    UNKNOWN when the guest's integration services report nothing.
"""

import json

import pytest

from app.models.virtual_machine import OSType
from app.services.discovery import _hyperv_os_type, _parse_hyperv_output


@pytest.mark.parametrize("os_name,expected", [
    ("Windows 10 Pro", OSType.WINDOWS),
    ("Windows Server 2019", OSType.WINDOWS),
    ("Ubuntu 22.04.3 LTS", OSType.LINUX),
    ("Debian GNU/Linux 12", OSType.LINUX),
    ("CentOS Stream 9", OSType.LINUX),
    ("Red Hat Enterprise Linux 9", OSType.LINUX),
    ("Alpine Linux v3.19", OSType.LINUX),
    ("FreeBSD 14", OSType.UNKNOWN),
    (None, OSType.UNKNOWN),
    ("", OSType.UNKNOWN),
])
def test_hyperv_os_type_classification(os_name, expected):
    assert _hyperv_os_type(os_name) == expected


def test_parse_uses_startup_ram_and_kvp_os():
    raw = json.dumps({
        "name": "win-vm",
        "source_uuid": "abc",
        "cpu_cores": 4,
        "memory_mb": 4096,          # MemoryStartup, not live MemoryAssigned
        "disk_gb": 40,
        "power_state": "running",
        "ip_address": None,
        "mac_address": "00155D000101",
        "hostname": "HV-HOST",
        "generation": 2,
        "os_name": "Windows Server 2022",
        "os_version": "10.0.20348",
    })
    [vm] = _parse_hyperv_output(raw)
    assert vm["memory_mb"] == 4096
    assert vm["os_type"] == OSType.WINDOWS
    assert vm["os_name"] == "Windows Server 2022"
    assert vm["os_version"] == "10.0.20348"
    assert vm["firmware"] == "efi"  # Generation 2


def test_parse_os_unknown_when_kvp_absent():
    """Guest with integration services down: os_name null → UNKNOWN, N/A."""
    raw = json.dumps({
        "name": "migration",
        "source_uuid": "4ac3fc8ccfda4bc1a0a527df1a15c912",
        "cpu_cores": 8,
        "memory_mb": 4096,
        "disk_gb": 10,
        "power_state": "running",
        "generation": 2,
        "os_name": None,
        "os_version": None,
    })
    [vm] = _parse_hyperv_output(raw)
    assert vm["os_type"] == OSType.UNKNOWN
    assert vm["os_name"] == "N/A"
    assert vm["os_version"] == "N/A"
    assert vm["memory_mb"] == 4096


def test_parse_generation1_is_bios():
    raw = json.dumps({
        "name": "legacy", "source_uuid": "x", "cpu_cores": 1,
        "memory_mb": 2048, "disk_gb": 20, "power_state": "stopped",
        "generation": 1, "os_name": "Ubuntu 18.04", "os_version": None,
    })
    [vm] = _parse_hyperv_output(raw)
    assert vm["firmware"] == "bios"
    assert vm["os_type"] == OSType.LINUX
