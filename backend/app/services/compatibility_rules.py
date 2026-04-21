"""
Compatibility rules engine for VM → OpenShift Virtualization migration.

Pure functions. No DB access. No I/O. Deterministic.

Each rule returns a dict:
    {
        "id":       str,    # stable rule identifier
        "passed":   bool,
        "severity": str,    # "BLOCKER" | "WARNING" | "INFO"
        "message":  str,    # human-readable explanation
        "weight":   int,    # contribution to the compatibility score
    }

Grading rules (applied by :func:`aggregate`):
  - any failed BLOCKER              → INCOMPATIBLE
  - else any failed WARNING          → PARTIAL
  - else                              → COMPATIBLE

Score = 100 * (sum of passed weights) / (sum of all weights), rounded.

This module is the single source of truth for labels used by
:mod:`app.ml.synthetic_data` — re-using :func:`evaluate_all` + :func:`aggregate`
to label synthetic samples keeps the training data aligned with runtime rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

# ---------------------------------------------------------------------------
# Grade constants
# ---------------------------------------------------------------------------

GRADE_COMPATIBLE = "COMPATIBLE"
GRADE_PARTIAL = "PARTIAL"
GRADE_INCOMPATIBLE = "INCOMPATIBLE"

# ---------------------------------------------------------------------------
# OS support matrix
# ---------------------------------------------------------------------------

_LINUX_DISTROS = (
    "ubuntu",
    "debian",
    "rhel",
    "red hat",
    "centos",
    "rocky",
    "alma",
    "fedora",
    "suse",
    "sles",
    "opensuse",
    "oracle",
)

_WINDOWS_SUPPORTED = (
    "windows server 2016",
    "windows server 2019",
    "windows server 2022",
    "windows 10",
    "windows 11",
)

# Minimum accepted major versions for Linux distributions (integer tolerant).
_LINUX_MIN_VERSION = {
    "ubuntu": 18,
    "debian": 10,
    "rhel": 7,
    "red hat": 7,
    "centos": 7,
    "rocky": 8,
    "alma": 8,
    "fedora": 32,
    "suse": 12,
    "sles": 12,
    "opensuse": 15,
    "oracle": 7,
}

# ---------------------------------------------------------------------------
# Disk format per hypervisor (D1 — Step 1 locked decision)
# ---------------------------------------------------------------------------

# Native KubeVirt-ingestible formats (no conversion needed).
_NATIVE_FORMATS = {"qcow2", "raw"}

# Convertible via qemu-img / virt-v2v.
_CONVERTIBLE_FORMATS = {"vmdk", "vhd", "vhdx"}

# Disk formats that cannot be migrated as-is (installation media, not disks).
_BLOCKER_FORMATS = {"iso"}

_HYPERVISOR_DEFAULT_FORMAT = {
    "vmware_workstation": "vmdk",
    "vsphere": "vmdk",
    "vmware_esxi": "vmdk",
    "hyper_v": "vhdx",
    "kvm": "qcow2",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _extract_linux_major(os_name: str, os_version: str) -> Optional[int]:
    """
    Extract the major version number from an OS name/version string.

    Examples:
        "Ubuntu 22.04 LTS", "22.04"  → 22
        "CentOS 7",         "7"       → 7
    Returns ``None`` when no integer can be parsed.
    """
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
    return None


def infer_disk_format(vm: Dict[str, Any]) -> str:
    """
    Derive the source disk format from the hypervisor type.

    D1 locked decision (Step 1): format is not stored in ``custom_metadata``
    today, so it is inferred from the hypervisor kind alone.

    Explicit override: vm["disk_format"] takes precedence when present —
    used by ``synthetic_data.py`` to inject ISO samples.
    """
    explicit = _norm(vm.get("disk_format"))
    if explicit:
        return explicit
    htype = _norm(vm.get("hypervisor_type"))
    return _HYPERVISOR_DEFAULT_FORMAT.get(htype, "unknown")


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def rule_os_supported(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    OS must be on the supported matrix.

    Hypervisor-specific: for Hyper-V and KVM, ``os_type == unknown`` is
    downgraded from BLOCKER to WARNING — see audit findings for the
    rationale (Hyper-V exposes no OS type without KVP; KVM relies on a
    name-keyword heuristic).
    """
    os_type = _norm(vm.get("os_type"))
    os_name = _norm(vm.get("os_name"))
    os_version = _norm(vm.get("os_version"))
    htype = _norm(vm.get("hypervisor_type"))

    combined = f"{os_name} {os_version}".strip()

    # Unknown OS on Hyper-V or KVM — soft PARTIAL, not blocker.
    if os_type == "unknown" and htype in ("hyper_v", "kvm"):
        hint = "Hyper-V n'expose pas le type d'OS sans KVP" if htype == "hyper_v" else (
            "KVM os_type dérivé par heuristique sur le nom de domaine"
        )
        return {
            "id": "os_supported",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": f"OS type UNKNOWN ({hint}) — migration possible mais vérification manuelle recommandée",
            "weight": 30,
        }

    if os_type == "linux":
        for distro in _LINUX_DISTROS:
            if distro in combined:
                min_major = _LINUX_MIN_VERSION.get(distro)
                actual = _extract_linux_major(os_name, os_version)
                if min_major is not None and actual is not None and actual < min_major:
                    return {
                        "id": "os_supported",
                        "passed": False,
                        "severity": SEVERITY_BLOCKER,
                        "message": f"{distro} {actual} en dessous du minimum supporté ({min_major}+)",
                        "weight": 30,
                    }
                return {
                    "id": "os_supported",
                    "passed": True,
                    "severity": SEVERITY_BLOCKER,
                    "message": f"Distribution Linux supportée: {distro}",
                    "weight": 30,
                }
        return {
            "id": "os_supported",
            "passed": False,
            "severity": SEVERITY_BLOCKER,
            "message": f"Distribution Linux non reconnue: {combined or 'inconnue'}",
            "weight": 30,
        }

    if os_type == "windows":
        for supported in _WINDOWS_SUPPORTED:
            if supported in combined:
                return {
                    "id": "os_supported",
                    "passed": True,
                    "severity": SEVERITY_BLOCKER,
                    "message": f"Windows supporté: {supported}",
                    "weight": 30,
                }
        return {
            "id": "os_supported",
            "passed": False,
            "severity": SEVERITY_BLOCKER,
            "message": f"Version Windows non supportée: {combined or 'inconnue'}",
            "weight": 30,
        }

    # os_type other/unknown on a hypervisor that *does* report OS info
    return {
        "id": "os_supported",
        "passed": False,
        "severity": SEVERITY_BLOCKER,
        "message": f"Type d'OS non supporté: {os_type or 'inconnu'}",
        "weight": 30,
    }


def rule_cpu_min(vm: Dict[str, Any]) -> Dict[str, Any]:
    """Minimum 1 vCPU."""
    cpu = int(vm.get("cpu_cores") or 0)
    passed = cpu >= 1
    return {
        "id": "cpu_min",
        "passed": passed,
        "severity": SEVERITY_BLOCKER,
        "message": (
            f"vCPU: {cpu} ≥ 1 requis"
            if passed
            else f"vCPU insuffisant: {cpu} (minimum 1)"
        ),
        "weight": 10,
    }


def rule_memory_min(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Memory thresholds:
      < 512 MB  → BLOCKER (incompatible)
      < 1024 MB → WARNING (partial)
      ≥ 1024 MB → pass
    """
    mem = int(vm.get("memory_mb") or 0)
    if mem < 512:
        return {
            "id": "memory_min",
            "passed": False,
            "severity": SEVERITY_BLOCKER,
            "message": f"RAM insuffisante: {mem} MB (< 512 MB)",
            "weight": 15,
        }
    if mem < 1024:
        return {
            "id": "memory_min",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": f"RAM faible: {mem} MB (< 1024 MB recommandé)",
            "weight": 15,
        }
    return {
        "id": "memory_min",
        "passed": True,
        "severity": SEVERITY_BLOCKER,
        "message": f"RAM: {mem} MB ≥ 1024 MB",
        "weight": 15,
    }


def rule_disk_min(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Minimum 10 GB disk. ``disk_gb == 0`` on KVM is a well-known artefact
    (``qemu-img info`` can silently return no virtual-size) — tolerated as
    a warning, not a failure.
    """
    disk = int(vm.get("disk_gb") or 0)
    htype = _norm(vm.get("hypervisor_type"))

    if disk == 0 and htype == "kvm":
        return {
            "id": "disk_min",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": "disk_gb=0 (artefact KVM — qemu-img info n'a pas retourné virtual-size)",
            "weight": 10,
        }
    if disk < 10:
        return {
            "id": "disk_min",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": f"Disque faible: {disk} GB (< 10 GB recommandé)",
            "weight": 10,
        }
    return {
        "id": "disk_min",
        "passed": True,
        "severity": SEVERITY_WARNING,
        "message": f"Disque: {disk} GB ≥ 10 GB",
        "weight": 10,
    }


def rule_disk_format(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disk format:
      qcow2 / raw  → native, pass
      vmdk / vhdx  → convertible (qemu-img / virt-v2v), WARNING
      iso          → BLOCKER (installation media, not a disk image)
    """
    fmt = infer_disk_format(vm)
    if fmt in _BLOCKER_FORMATS:
        return {
            "id": "disk_format",
            "passed": False,
            "severity": SEVERITY_BLOCKER,
            "message": f"Format disque non migrable: {fmt} (média d'installation)",
            "weight": 20,
        }
    if fmt in _CONVERTIBLE_FORMATS:
        return {
            "id": "disk_format",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": f"Format disque convertible: {fmt} → qcow2 via qemu-img",
            "weight": 20,
        }
    if fmt in _NATIVE_FORMATS:
        return {
            "id": "disk_format",
            "passed": True,
            "severity": SEVERITY_BLOCKER,
            "message": f"Format disque natif KubeVirt: {fmt}",
            "weight": 20,
        }
    return {
        "id": "disk_format",
        "passed": False,
        "severity": SEVERITY_WARNING,
        "message": f"Format disque inconnu: {fmt or 'non déterminé'}",
        "weight": 20,
    }


def rule_drivers_virtio(vm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Driver availability (inferred — guest tools data is often absent).

    Linux guests: virtio-net / virtio-blk are in the mainline kernel since 2.6.25;
    assumed present. Windows guests: virtio drivers must be injected at migration
    time — surfaced as a WARNING so the migration engine knows to run virt-v2v or
    inject the Fedora virtio-win ISO.
    """
    os_type = _norm(vm.get("os_type"))
    if os_type == "linux":
        return {
            "id": "drivers_virtio",
            "passed": True,
            "severity": SEVERITY_WARNING,
            "message": "Linux: virtio-net / virtio-blk supposés présents (kernel mainline)",
            "weight": 5,
        }
    if os_type == "windows":
        return {
            "id": "drivers_virtio",
            "passed": False,
            "severity": SEVERITY_WARNING,
            "message": "Windows: injection virtio-win requise lors de la migration",
            "weight": 5,
        }
    return {
        "id": "drivers_virtio",
        "passed": False,
        "severity": SEVERITY_WARNING,
        "message": "Drivers virtio: OS inconnu — vérification manuelle",
        "weight": 5,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_RULE_FUNCTIONS = (
    rule_os_supported,
    rule_cpu_min,
    rule_memory_min,
    rule_disk_min,
    rule_disk_format,
    rule_drivers_virtio,
)


def evaluate_all(vm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run every rule against the VM dict and return a list of rule results."""
    return [fn(vm) for fn in _RULE_FUNCTIONS]


def aggregate(rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Derive the grade, numeric score, blocker list and warning list from the
    rule results.
    """
    blockers: List[str] = []
    warnings: List[str] = []
    total_weight = 0
    passed_weight = 0

    for rule in rules:
        total_weight += rule["weight"]
        if rule["passed"]:
            passed_weight += rule["weight"]
            continue
        if rule["severity"] == SEVERITY_BLOCKER:
            blockers.append(rule["message"])
        elif rule["severity"] == SEVERITY_WARNING:
            warnings.append(rule["message"])

    score = round(100 * passed_weight / total_weight) if total_weight else 0

    if blockers:
        grade = GRADE_INCOMPATIBLE
    elif warnings:
        grade = GRADE_PARTIAL
    else:
        grade = GRADE_COMPATIBLE

    return {
        "grade": grade,
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
    }
