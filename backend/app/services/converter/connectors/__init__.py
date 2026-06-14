"""
Connector registry — maps :class:`HypervisorType` to a :class:`DiskPuller`.

Lookup is dispatched by :func:`get_puller` so the converter service never
imports connectors directly.
"""

from __future__ import annotations

from app.models.hypervisor import HypervisorType
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import DiskPuller

from app.services.converter.connectors.hyperv import HyperVPuller
from app.services.converter.connectors.kvm import KvmPuller
from app.services.converter.connectors.ovirt import OvirtPuller
from app.services.converter.connectors.proxmox import ProxmoxPuller
from app.services.converter.connectors.vmware_workstation import VmwareWorkstationPuller
from app.services.converter.connectors.vsphere import VsphereStubPuller


_REGISTRY: dict[HypervisorType, type[DiskPuller]] = {
    HypervisorType.PROXMOX: ProxmoxPuller,
    HypervisorType.KVM: KvmPuller,
    HypervisorType.VMWARE_WORKSTATION: VmwareWorkstationPuller,
    HypervisorType.HYPER_V: HyperVPuller,
    HypervisorType.OVIRT: OvirtPuller,
    HypervisorType.VSPHERE: VsphereStubPuller,
    # ESXi standalone hosts register under either enum value; both use the
    # same pyVmomi/datastore connector.
    HypervisorType.VMWARE_ESXi: VsphereStubPuller,
}


def get_puller(hv_type: HypervisorType) -> DiskPuller:
    """Return a puller instance for the given hypervisor type.

    Raises ``ConversionError(ERR_UNSUPPORTED_HYPERVISOR)`` if no connector
    is registered.
    """
    cls = _REGISTRY.get(hv_type)
    if cls is None:
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            f"No converter connector for hypervisor type {hv_type.value}",
        )
    return cls()


__all__ = ["get_puller"]
