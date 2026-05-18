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


@pytest.mark.parametrize("host", [
    "127.0.0.1",
    "127.0.0.53",
    "::1",
    "qemu+ssh://root@127.0.0.1/system",
])
def test_loopback_hosts_rejected(host):
    """Audit A5 — la loopback (127.0.0.0/8, ::1) est interdite : un
    hyperviseur ne réside jamais sur la boucle locale du backend ;
    l'autoriser ouvrirait un SSRF vers les services co-localisés."""
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


# ---------------------------------------------------------------------------
# Audit A5 — validation de connection_config (api_path, ssh_key_path)
# ---------------------------------------------------------------------------


def _create_cfg(cfg: dict) -> HypervisorCreate:
    return HypervisorCreate(
        name="hv", type=HypervisorType.OVIRT, host="10.9.21.131",
        username="u", password="p", connection_config=cfg,
    )


def test_connection_config_valid_accepted():
    """Un connection_config légitime passe et les valeurs sont normalisées."""
    hv = _create_cfg({
        "api_path": "/ovirt-engine/api",
        "ssh_key_path": "/etc/shiftwise/ssh/kvm_id_rsa",
        "datacenter": "DC1",
    })
    assert hv.connection_config["api_path"] == "/ovirt-engine/api"
    assert hv.connection_config["ssh_key_path"] == "/etc/shiftwise/ssh/kvm_id_rsa"
    assert hv.connection_config["datacenter"] == "DC1"


def test_connection_config_none_and_empty_ok():
    """Absence de connection_config, ou dict sans clé sensible, est accepté."""
    assert _create_cfg({}).connection_config == {}
    hv = HypervisorCreate(
        name="hv", type=HypervisorType.KVM, host="10.9.21.131",
        username="u", password="p",
    )
    assert hv.connection_config is None


@pytest.mark.parametrize("api_path", [
    "ovirt-engine/api",                       # pas de '/' initial
    "//evil.example.com/api",                 # interprété comme hôte réseau
    "https://evil.example.com/api",           # schéma + hôte
    "/ovirt-engine/../../etc/passwd",          # traversée '..'
    "/api\r\nHost: evil.example.com",          # caractère de contrôle / CRLF
])
def test_connection_config_api_path_rejected(api_path):
    with pytest.raises(ValidationError):
        _create_cfg({"api_path": api_path})


@pytest.mark.parametrize("ssh_key_path", [
    "relative/key",                            # pas absolu
    "id_rsa",                                  # pas absolu
    "/etc/shiftwise/ssh/../../root/.ssh/id_rsa",  # traversée '..'
    "/root/.ssh/id_rsa",                       # absolu mais hors racine autorisée
    "/etc/shiftwise/ssh/key\x00",              # caractère de contrôle (NUL)
])
def test_connection_config_ssh_key_path_rejected(ssh_key_path):
    with pytest.raises(ValidationError):
        _create_cfg({"ssh_key_path": ssh_key_path})


def test_connection_config_validation_applies_to_update():
    """Audit A5 — la validation s'applique aussi à HypervisorUpdate."""
    with pytest.raises(ValidationError):
        HypervisorUpdate(connection_config={"ssh_key_path": "/root/.ssh/id_rsa"})
    with pytest.raises(ValidationError):
        HypervisorUpdate(connection_config={"api_path": "https://evil.example.com"})
    # Une mise à jour valide passe.
    ok = HypervisorUpdate(connection_config={"api_path": "/ovirt-engine/api"})
    assert ok.connection_config["api_path"] == "/ovirt-engine/api"
