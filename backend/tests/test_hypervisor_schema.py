"""
Tests de validation du schéma Hypervisor.

Couvre H-03 (SSRF) : le champ `host` ne doit pas pouvoir cibler une plage
link-local — typiquement le endpoint de métadonnées cloud 169.254.169.254 —
ni l'adresse non spécifiée.
"""

import pytest
from pydantic import ValidationError

from app.models.hypervisor import HypervisorType
from app.schemas.hypervisor import (
    HypervisorCreate,
    HypervisorTestConnection,
    HypervisorUpdate,
    _check_host_not_ssrf,
)


def _create(host: str) -> HypervisorCreate:
    return HypervisorCreate(
        name="hv", type=HypervisorType.KVM, host=host,
        username="u", password="p",
    )


@pytest.mark.parametrize("host", [
    "10.9.21.131",
    "192.168.1.69",
    "esxi.lab.example.com",
    "qemu+ssh://ubuntu@10.9.21.131/system",
    "localhost",
])
def test_legitimate_hosts_accepted(host):
    assert _check_host_not_ssrf(host) == host
    _create(host)  # ne doit lever aucune exception


@pytest.mark.parametrize("host", [
    "169.254.169.254",
    "169.254.0.1",
    "qemu+ssh://root@169.254.169.254/system",
    "0.0.0.0",
])
def test_link_local_and_unspecified_hosts_rejected(host):
    with pytest.raises(ValueError):
        _check_host_not_ssrf(host)
    with pytest.raises(ValidationError):
        _create(host)


def test_ssrf_check_applies_to_update_and_test_connection():
    with pytest.raises(ValidationError):
        HypervisorUpdate(host="169.254.169.254")
    with pytest.raises(ValidationError):
        HypervisorTestConnection(
            type=HypervisorType.PROXMOX, host="169.254.169.254",
            username="u", password="p",
        )
