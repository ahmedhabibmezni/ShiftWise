"""
Hostname / IP capture across discovery connectors (Issue 2).

The virsh XML (KVM) and the Proxmox API expose no guest hostname, and the
Proxmox API exposes no IP outside the guest agent — so without an explicit
agent probe both fields stayed null on every KVM/Proxmox VM. These tests pin
the best-effort agent lookups and their graceful fallbacks.
"""

from __future__ import annotations

from app.services.discovery import DiscoveryService, _parse_proxmox_vm


# ---------------------------------------------------------------------------
# Proxmox — guest-agent hostname threaded into the VM dict
# ---------------------------------------------------------------------------

def _proxmox_resource(status: str = "running") -> dict:
    return {"vmid": 100, "node": "pve", "name": "alpine-pg-demo", "status": status}


def test_proxmox_hostname_from_agent():
    vm = _parse_proxmox_vm(
        _proxmox_resource(), {"bios": "seabios"}, agent_hostname="pg-prod-01",
    )
    assert vm["hostname"] == "pg-prod-01"


def test_proxmox_hostname_none_without_agent():
    # No agent answer → null (the inventory "name" is NOT reported as hostname).
    vm = _parse_proxmox_vm(_proxmox_resource(), {})
    assert vm["hostname"] is None
    assert vm["name"] == "alpine-pg-demo"


# ---------------------------------------------------------------------------
# KVM — guest-agent IP / hostname helpers (parse a fake `run` callable)
# ---------------------------------------------------------------------------

_DOMIFADDR_AGENT = (
    " Name       MAC address          Protocol     Address\n"
    "-------------------------------------------------------------------------------\n"
    " lo         00:00:00:00:00:00    ipv4         127.0.0.1/8\n"
    " enp1s0     52:54:00:aa:bb:cc    ipv4         192.168.1.50/24\n"
)

_GUEST_HOSTNAME_JSON = '{"return":{"host-name":"pg-prod-01"}}'


def _runner(responses: dict):
    """Build a fake virsh `run` returning (out, err, rc) keyed by substring."""
    def run(cmd: str):
        for needle, (out, rc) in responses.items():
            if needle in cmd:
                return out, "", rc
        return "", "not found", 1
    return run


def test_kvm_guest_ipv4_skips_loopback():
    run = _runner({"domifaddr": (_DOMIFADDR_AGENT, 0)})
    assert DiscoveryService._kvm_guest_ipv4(run, "'vm'") == "192.168.1.50"


def test_kvm_guest_ipv4_none_when_agent_silent():
    run = _runner({})  # both agent + lease sources fail
    assert DiscoveryService._kvm_guest_ipv4(run, "'vm'") is None


def test_kvm_guest_hostname_from_agent():
    run = _runner({"guest-get-host-name": (_GUEST_HOSTNAME_JSON, 0)})
    assert DiscoveryService._kvm_guest_hostname(run, "'vm'") == "pg-prod-01"


def test_kvm_guest_hostname_none_on_bad_json():
    run = _runner({"guest-get-host-name": ("not json", 0)})
    assert DiscoveryService._kvm_guest_hostname(run, "'vm'") is None


def test_kvm_guest_hostname_none_when_agent_fails():
    run = _runner({})
    assert DiscoveryService._kvm_guest_hostname(run, "'vm'") is None
