"""
Universal firmware (UEFI/BIOS) capture across discovery connectors.

Every connector must report a ``firmware`` key ("efi" | "bios") so the migrator
can emit the matching KubeVirt firmware. A UEFI guest booted under the SeaBIOS
default (or vice-versa) hangs at boot, so this is detected per source.
"""

from __future__ import annotations

from app.services.discovery import (
    _normalize_firmware,
    _parse_hyperv_output,
    _parse_kvm_domain_xml,
    _parse_proxmox_vm,
)


def test_normalize_firmware_mappings():
    for efi in ("efi", "EFI", "ovmf", "uefi", "q35_ovmf", "q35_secure_boot", "pflash-efi"):
        assert _normalize_firmware(efi) == "efi"
    for bios in ("bios", "seabios", "q35_sea_bios", "i440fx_sea_bios"):
        assert _normalize_firmware(bios) == "bios"
    for unknown in (None, "", "cluster_default", "weird"):
        assert _normalize_firmware(unknown) is None


def test_proxmox_firmware_ovmf_is_uefi():
    res = {"vmid": 100, "node": "pve", "name": "vm", "status": "running"}
    assert _parse_proxmox_vm(res, {"bios": "ovmf"})["firmware"] == "efi"
    # seabios and absent both fall back to BIOS.
    assert _parse_proxmox_vm(res, {"bios": "seabios"})["firmware"] == "bios"
    assert _parse_proxmox_vm(res, {})["firmware"] == "bios"


_KVM_BIOS_XML = """
<domain type='kvm'>
  <name>legacy</name><uuid>11111111-1111-1111-1111-111111111111</uuid>
  <vcpu>2</vcpu><memory unit='KiB'>2097152</memory>
  <os><type arch='x86_64' machine='pc-q35'>hvm</type></os>
  <devices><interface type='network'><mac address='52:54:00:aa:bb:cc'/></interface></devices>
</domain>
"""

_KVM_UEFI_XML = """
<domain type='kvm'>
  <name>modern</name><uuid>22222222-2222-2222-2222-222222222222</uuid>
  <vcpu>2</vcpu><memory unit='KiB'>2097152</memory>
  <os firmware='efi'>
    <type arch='x86_64' machine='pc-q35'>hvm</type>
    <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
    <nvram>/var/lib/libvirt/qemu/nvram/modern_VARS.fd</nvram>
  </os>
  <devices/>
</domain>
"""


def test_kvm_firmware_detection():
    assert _parse_kvm_domain_xml(_KVM_BIOS_XML, "running", {})["firmware"] == "bios"
    assert _parse_kvm_domain_xml(_KVM_UEFI_XML, "running", {})["firmware"] == "efi"


def test_hyperv_generation_maps_to_firmware():
    gen2 = '{"name":"win","source_uuid":"abc","generation":2}'
    gen1 = '{"name":"dos","source_uuid":"def","generation":1}'
    assert _parse_hyperv_output(gen2)[0]["firmware"] == "efi"
    assert _parse_hyperv_output(gen1)[0]["firmware"] == "bios"
