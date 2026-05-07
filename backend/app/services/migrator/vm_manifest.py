"""
KubeVirt VirtualMachine manifest builder.

Conventions:
    - disk_index == 0 is the boot disk (mapped to ``bootOrder: 1``)
    - all disks use ``virtio`` bus — KubeVirt injects virtio drivers via
      virtio-win container disks for Windows guests, but we don't add that
      here (out of scope for the first cut)
    - one network interface per VM, masquerade-bound (pod network) — multi-NIC
      requires NetworkAttachmentDefinitions which are namespace-scoped and
      out of scope for now
    - ``runStrategy: Halted`` on creation, then explicitly transitioned to
      ``Always`` by the orchestrator after VM create succeeds (lets us
      separate the create error from the boot error in status reporting)

The output is a plain dict suitable for
``CustomObjectsApi.create_namespaced_custom_object(group="kubevirt.io", ...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.models.virtual_machine import OSType


_DNS_LABEL_RE = re.compile(r"[^a-z0-9-]")
_MAX_VM_NAME_LEN = 63


@dataclass(frozen=True)
class DiskSpec:
    """One disk reference for the VM manifest."""
    disk_index: int
    pvc_name: str
    is_boot: bool


def sanitize_vm_name(raw: str, fallback: str) -> str:
    """Coerce a free-form name into a DNS-1123 label.

    KubeVirt object names must match ``[a-z0-9]([-a-z0-9]*[a-z0-9])?``,
    max 63 chars. We lowercase, replace invalid chars with ``-``, strip
    leading/trailing dashes, and fall back to ``fallback`` if the result
    is empty.
    """
    candidate = _DNS_LABEL_RE.sub("-", (raw or "").lower()).strip("-")
    candidate = re.sub(r"-+", "-", candidate)[:_MAX_VM_NAME_LEN].strip("-")
    return candidate or fallback


def build_virtual_machine(
    *,
    name: str,
    namespace: str,
    cpu_cores: int,
    memory_mb: int,
    disks: list[DiskSpec],
    os_type: OSType,
    mac_address: Optional[str] = None,
    migration_id: Optional[int] = None,
    source_vm_id: Optional[int] = None,
    extra_labels: Optional[dict[str, str]] = None,
) -> dict:
    """Build a KubeVirt VirtualMachine custom resource as a plain dict."""
    if not disks:
        raise ValueError("at least one disk is required")
    if cpu_cores < 1:
        raise ValueError("cpu_cores must be >= 1")
    if memory_mb < 128:
        raise ValueError("memory_mb must be >= 128")

    labels = {
        "kubevirt.io/vm": name,
        "app.shiftwise.io/managed": "true",
    }
    if migration_id is not None:
        labels["app.shiftwise.io/migration-id"] = str(migration_id)
    if source_vm_id is not None:
        labels["app.shiftwise.io/source-vm-id"] = str(source_vm_id)
    if extra_labels:
        labels.update(extra_labels)

    sorted_disks = sorted(disks, key=lambda d: d.disk_index)
    disk_devices = [_build_disk_device(d) for d in sorted_disks]
    volumes = [_build_volume(d) for d in sorted_disks]

    interface, network = _build_pod_network(mac_address)

    return {
        "apiVersion": "kubevirt.io/v1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            # Halted on create — orchestrator flips to Always after success
            # to separate create-vs-start failure surfaces.
            "runStrategy": "Halted",
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "domain": {
                        "cpu": {"cores": int(cpu_cores)},
                        "memory": {"guest": f"{int(memory_mb)}Mi"},
                        "devices": {
                            "disks": disk_devices,
                            "interfaces": [interface],
                            "networkInterfaceMultiqueue": True,
                            # Serial console enabled — paired with the
                            # adapter that enables serial-getty@ttyS0
                            # inside the guest. Without this stanza,
                            # virtctl console connects but never sees
                            # output (incident 2026-05-04).
                            "autoattachSerialConsole": True,
                            **_os_specific_devices(os_type),
                        },
                        "machine": _machine(),
                    },
                    "networks": [network],
                    "volumes": volumes,
                    "terminationGracePeriodSeconds": 180,
                    # RWO PVC + LiveMigrate is incompatible. KubeVirt's
                    # eviction warning loops are noisy and confusing in
                    # prod. Default to None until we have RWX storage; the
                    # operator can override per-VM if they know better.
                    "evictionStrategy": "None",
                },
            },
        },
    }


# --- internals -------------------------------------------------------------

def _build_disk_device(d: DiskSpec) -> dict:
    device: dict = {
        "name": f"disk-{d.disk_index}",
        "disk": {"bus": "virtio"},
    }
    if d.is_boot:
        device["bootOrder"] = 1
    return device


def _build_volume(d: DiskSpec) -> dict:
    return {
        "name": f"disk-{d.disk_index}",
        "persistentVolumeClaim": {"claimName": d.pvc_name},
    }


def _build_pod_network(mac_address: Optional[str]) -> tuple[dict, dict]:
    """Single masquerade-bound interface on the default pod network."""
    interface: dict = {
        "name": "default",
        "masquerade": {},
        "model": "virtio",
    }
    if mac_address:
        interface["macAddress"] = mac_address
    network = {"name": "default", "pod": {}}
    return interface, network


def _os_specific_devices(os_type: OSType) -> dict:
    """Adds a tablet pointer for Windows guests (virtio mouse is unreliable)."""
    if os_type == OSType.WINDOWS:
        return {
            "inputs": [{
                "type": "tablet",
                "name": "tablet",
                "bus": "usb",
            }],
        }
    return {}


def _machine() -> dict:
    # q35 is the modern PC chipset KubeVirt defaults to; explicit for clarity.
    return {"type": "q35"}
