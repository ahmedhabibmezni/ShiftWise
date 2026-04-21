"""
Feature extractor — single source of truth shared between training
(:mod:`app.ml.train_model`) and runtime prediction (:mod:`app.services.analyzer`).

Contract
--------
- :func:`rules_features` — takes any VM-like dict and returns a flat named
  feature dict. Used for introspection and tests.
- :func:`to_vector` — converts that dict into a fixed-shape numeric vector
  whose column order matches :data:`FEATURE_NAMES` exactly. The model is
  trained on this vector; any change to :data:`FEATURE_NAMES` requires
  regenerating the ``.joblib`` artifact.

Uncovered fields from the connector audit (``tools_state``, ``vmx_path``
outside VMware Workstation) are encoded as explicit ``"unknown"`` — never
silently imputed (locked rule in NEXT_STEPS).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.compatibility_rules import infer_disk_format

# ---------------------------------------------------------------------------
# Stable vocabularies
# ---------------------------------------------------------------------------

_OS_TYPES = ("linux", "windows", "other", "unknown")

_OS_FAMILIES = (
    "ubuntu",
    "debian",
    "rhel",
    "centos",
    "fedora",
    "suse",
    "windows_server",
    "windows_client",
    "other",
    "unknown",
)

_HYPERVISOR_TYPES = (
    "vmware_workstation",
    "vsphere",
    "vmware_esxi",
    "hyper_v",
    "kvm",
    "other",
    "unknown",
)

_DISK_FORMATS = ("qcow2", "raw", "vmdk", "vhd", "vhdx", "iso", "unknown")

_POWER_STATES = ("running", "stopped", "paused", "poweredoff", "unknown")

_TOOLS_STATES = ("installed", "running", "unknown")


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _one_hot(value: str, vocab: tuple) -> Dict[str, int]:
    """One-hot encode ``value`` over ``vocab``. Unknown values collapse to 'other'/'unknown'."""
    v = value if value in vocab else ("unknown" if "unknown" in vocab else "other")
    return {item: (1 if item == v else 0) for item in vocab}


def _detect_os_family(os_type: str, os_name: str) -> str:
    name = os_name.lower()
    if os_type == "linux":
        for distro in ("ubuntu", "debian", "rhel", "centos", "fedora", "suse"):
            if distro in name or (distro == "rhel" and "red hat" in name):
                return distro
        return "other"
    if os_type == "windows":
        if "server" in name:
            return "windows_server"
        return "windows_client"
    if os_type == "unknown" or not os_type:
        return "unknown"
    return "other"


def _extract_os_major(os_name: str, os_version: str) -> int:
    """Return the first integer found in os_version (then os_name), or -1."""
    for candidate in (os_version, os_name):
        if not candidate:
            continue
        digits = ""
        for ch in candidate:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if digits:
            try:
                return int(digits)
            except ValueError:
                continue
    return -1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rules_features(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the named feature dictionary for a VM.

    ``vm`` is the VM row as a plain dict (ORM ``to_dict()`` output, synthetic
    sample dict, or connector discovery dict).  Every key accessed here has
    a sensible fallback — the extractor never raises on missing fields.
    """
    cpu = int(vm.get("cpu_cores") or 0)
    memory = int(vm.get("memory_mb") or 0)
    disk = int(vm.get("disk_gb") or 0)

    os_type = _norm(vm.get("os_type")) or "unknown"
    os_name = _norm(vm.get("os_name"))
    os_version = _norm(vm.get("os_version"))
    os_family = _detect_os_family(os_type, os_name)
    os_major = _extract_os_major(os_name, os_version)

    hypervisor_type = _norm(vm.get("hypervisor_type")) or "unknown"
    disk_format = infer_disk_format(vm)

    # custom_metadata-derived fields — explicit "unknown" when absent
    meta = vm.get("custom_metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    power_state = _norm(meta.get("power_state")) or "unknown"
    tools_state = _norm(meta.get("tools_state")) or "unknown"
    has_vmx_path = 1 if meta.get("vmx_path") else 0

    features: Dict[str, Any] = {
        "cpu_cores": cpu,
        "memory_mb": memory,
        "disk_gb": disk,
        "os_major_version": os_major,
        "has_vmx_path": has_vmx_path,
    }
    features.update({f"os_type_{k}": v for k, v in _one_hot(os_type, _OS_TYPES).items()})
    features.update({f"os_family_{k}": v for k, v in _one_hot(os_family, _OS_FAMILIES).items()})
    features.update(
        {f"hypervisor_type_{k}": v for k, v in _one_hot(hypervisor_type, _HYPERVISOR_TYPES).items()}
    )
    features.update({f"disk_format_{k}": v for k, v in _one_hot(disk_format, _DISK_FORMATS).items()})
    features.update({f"power_state_{k}": v for k, v in _one_hot(power_state, _POWER_STATES).items()})
    features.update({f"tools_state_{k}": v for k, v in _one_hot(tools_state, _TOOLS_STATES).items()})

    return features


# Canonical column order — the model is trained against this exact sequence.
FEATURE_NAMES: tuple = (
    "cpu_cores",
    "memory_mb",
    "disk_gb",
    "os_major_version",
    "has_vmx_path",
    *[f"os_type_{k}" for k in _OS_TYPES],
    *[f"os_family_{k}" for k in _OS_FAMILIES],
    *[f"hypervisor_type_{k}" for k in _HYPERVISOR_TYPES],
    *[f"disk_format_{k}" for k in _DISK_FORMATS],
    *[f"power_state_{k}" for k in _POWER_STATES],
    *[f"tools_state_{k}" for k in _TOOLS_STATES],
)


def to_vector(features: Dict[str, Any]) -> List[float]:
    """Convert a feature dict into an ordered numeric vector."""
    return [float(features.get(name, 0)) for name in FEATURE_NAMES]


def extract_vector(vm: Dict[str, Any]) -> List[float]:
    """Shortcut: ``to_vector(rules_features(vm))``."""
    return to_vector(rules_features(vm))
