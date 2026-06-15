"""
Synthetic dataset generator for the compatibility classifier.

Dev tooling only — not imported at runtime.

Design
------
- Size: 1500–2000 samples (default 1800).
- Class balance: ~40 % COMPATIBLE / 35 % PARTIAL / 25 % INCOMPATIBLE.
- Labels are derived from :mod:`app.services.compatibility_rules` so that the
  training targets are aligned with the runtime rule engine.
- Anti-circularity:
    * 5–10 % controlled label noise (flip two grades to a neighbour class).
    * 50–100 hand-crafted adversarial borderline samples (ambiguous OS strings,
      mixed resource signals, edge values).

The rationale is documented in the rapport: the ML model's contribution over
the pure rule engine is **robustness on ambiguous / noisy inputs**, not the
discovery of new compatibility rules.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from app.services.compatibility_rules import aggregate, evaluate_all

_LINUX_SAMPLES = [
    ("linux", "Ubuntu 22.04 LTS", "22.04"),
    ("linux", "Ubuntu 20.04", "20.04"),
    ("linux", "Ubuntu 18.04", "18.04"),
    ("linux", "Debian 11", "11"),
    ("linux", "Debian 12", "12"),
    ("linux", "CentOS 7", "7"),
    ("linux", "CentOS 8 Stream", "8"),
    ("linux", "Rocky Linux 9", "9"),
    ("linux", "AlmaLinux 8", "8"),
    ("linux", "RHEL 8", "8"),
    ("linux", "RHEL 9", "9"),
    ("linux", "Fedora 38", "38"),
    ("linux", "SUSE Linux Enterprise 15", "15"),
    ("linux", "openSUSE Leap 15.5", "15.5"),
    ("linux", "Oracle Linux 8", "8"),
]

_LINUX_UNSUPPORTED = [
    ("linux", "Ubuntu 16.04", "16.04"),
    ("linux", "CentOS 6", "6"),
    ("linux", "Debian 8", "8"),
    ("linux", "Gentoo", ""),
    ("linux", "Arch Linux", ""),
]

_WINDOWS_SUPPORTED = [
    ("windows", "Windows Server 2016", "2016"),
    ("windows", "Windows Server 2019", "2019"),
    ("windows", "Windows Server 2022", "2022"),
    ("windows", "Windows 10 Pro", "10"),
    ("windows", "Windows 11 Pro", "11"),
]

_WINDOWS_UNSUPPORTED = [
    ("windows", "Windows Server 2008 R2", "2008"),
    ("windows", "Windows Server 2012", "2012"),
    ("windows", "Windows 7", "7"),
    ("windows", "Windows XP", "xp"),
]

_HYPERVISORS = ("vmware_workstation", "hyper_v", "kvm", "vsphere", "proxmox", "ovirt", "physical")

# Virtio-native sources need no guest adaptation — only these can be truly
# COMPATIBLE (score 100) under the intervention-based rules engine.
_VIRTIO_NATIVE = ("kvm", "proxmox", "ovirt")


def _base_custom_metadata(hypervisor_type: str, power: str, rng: random.Random) -> Dict[str, Any]:
    """Mirror the connector audit: only VMware WS sets vmx_path + tools_state."""
    meta: Dict[str, Any] = {"power_state": power}
    if hypervisor_type == "vmware_workstation":
        meta["vmx_path"] = f"C:/VMs/sample_{rng.randint(1000, 9999)}.vmx"
        meta["tools_state"] = rng.choice(["installed", "running", "unknown"])
    return meta


def _make_sample(
    rng: random.Random,
    os_type: str,
    os_name: str,
    os_version: str,
    hypervisor_type: str,
    cpu: int,
    memory: int,
    disk: int,
    disk_format_override: str = "",
    power: str = "running",
) -> Dict[str, Any]:
    vm: Dict[str, Any] = {
        "cpu_cores": cpu,
        "memory_mb": memory,
        "disk_gb": disk,
        "os_type": os_type,
        "os_name": os_name,
        "os_version": os_version,
        "hypervisor_type": hypervisor_type,
        "custom_metadata": _base_custom_metadata(hypervisor_type, power, rng),
    }
    if disk_format_override:
        vm["disk_format"] = disk_format_override
    return vm


# ---------------------------------------------------------------------------
# Generators per target grade
# ---------------------------------------------------------------------------


def _gen_compatible(rng: random.Random) -> Dict[str, Any]:
    os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES + _WINDOWS_SUPPORTED)
    # Only virtio-native sources (KVM/Proxmox/oVirt) can be truly COMPATIBLE:
    # every other source needs guest adaptation (NIC→virtio) which the
    # intervention-based rules engine scores as a warning → PARTIAL. Physical
    # also needs initramfs virtio injection, so it belongs in _gen_partial.
    hypervisor_type = rng.choice(_VIRTIO_NATIVE)
    cpu = rng.randint(2, 16)
    memory = rng.choice([2048, 4096, 8192, 16384, 32768])
    disk = rng.randint(20, 500)
    return _make_sample(rng, os_type, os_name, os_version, hypervisor_type, cpu, memory, disk)


def _gen_partial(rng: random.Random) -> Dict[str, Any]:
    """
    Partial = warnings only, no blockers.
    Triggers:
      - VMware WS / Hyper-V / vSphere (convertible disk format) on a supported OS
      - Hyper-V with UNKNOWN os_type (the dedicated rule)
      - KVM with disk_gb=0
      - 512 ≤ memory < 1024
      - disk < 10 GB (but > 0)
    """
    scenario = rng.choice(("convertible_format", "hyperv_unknown", "kvm_zero_disk",
                            "low_memory", "small_disk", "kvm_unknown",
                            "proxmox_unknown", "ovirt_unknown",
                            "physical_low_memory"))

    if scenario == "convertible_format":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES + _WINDOWS_SUPPORTED)
        hypervisor_type = rng.choice(("vmware_workstation", "hyper_v", "vsphere"))
        return _make_sample(rng, os_type, os_name, os_version, hypervisor_type,
                            rng.randint(2, 8), rng.choice([2048, 4096, 8192]),
                            rng.randint(20, 200))

    if scenario == "hyperv_unknown":
        return _make_sample(rng, "unknown", "", "", "hyper_v",
                            rng.randint(1, 8), rng.choice([2048, 4096, 8192]),
                            rng.randint(20, 200))

    if scenario == "kvm_unknown":
        return _make_sample(rng, "unknown", "", "", "kvm",
                            rng.randint(1, 8), rng.choice([2048, 4096, 8192]),
                            rng.randint(20, 200))

    if scenario == "proxmox_unknown":
        return _make_sample(rng, "unknown", "", "", "proxmox",
                            rng.randint(1, 8), rng.choice([2048, 4096, 8192]),
                            rng.randint(20, 200))

    if scenario == "ovirt_unknown":
        return _make_sample(rng, "unknown", "", "", "ovirt",
                            rng.randint(1, 8), rng.choice([2048, 4096, 8192]),
                            rng.randint(20, 200))

    if scenario == "kvm_zero_disk":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version, "kvm",
                            rng.randint(1, 4), rng.choice([1024, 2048, 4096]), 0)

    if scenario == "low_memory":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version, "kvm",
                            rng.randint(1, 2), rng.randint(512, 1023),
                            rng.randint(20, 100))

    if scenario == "physical_low_memory":
        # Physical P2V (raw = native format), supported OS, but under-provisioned
        # RAM → only the low-memory warning fires → PARTIAL.
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version, "physical",
                            rng.randint(1, 2), rng.randint(512, 1023),
                            rng.randint(20, 100))

    # small_disk
    os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
    return _make_sample(rng, os_type, os_name, os_version, "kvm",
                        rng.randint(1, 2), 1024, rng.randint(1, 9))


def _gen_incompatible(rng: random.Random) -> Dict[str, Any]:
    """
    Incompatible = at least one blocker.
    Triggers: ISO disk format, memory < 512, unsupported OS.
    """
    scenario = rng.choice(("iso_format", "tiny_memory", "unsupported_os",
                            "zero_cpu", "old_linux", "old_windows"))

    if scenario == "iso_format":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version,
                            rng.choice(_HYPERVISORS),
                            rng.randint(1, 4), 2048, rng.randint(10, 50),
                            disk_format_override="iso")

    if scenario == "tiny_memory":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version, "kvm",
                            1, rng.randint(64, 511), rng.randint(10, 50))

    if scenario == "unsupported_os":
        return _make_sample(rng, "other", "Solaris 10", "10",
                            rng.choice(_HYPERVISORS),
                            rng.randint(1, 4), 2048, rng.randint(20, 100))

    if scenario == "zero_cpu":
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        return _make_sample(rng, os_type, os_name, os_version, "kvm",
                            0, 2048, 20)

    if scenario == "old_linux":
        os_type, os_name, os_version = rng.choice(_LINUX_UNSUPPORTED)
        return _make_sample(rng, os_type, os_name, os_version, "kvm",
                            rng.randint(1, 4), 2048, rng.randint(20, 100))

    # old_windows
    os_type, os_name, os_version = rng.choice(_WINDOWS_UNSUPPORTED)
    return _make_sample(rng, os_type, os_name, os_version,
                        rng.choice(_HYPERVISORS),
                        rng.randint(1, 4), 2048, rng.randint(20, 100))


# ---------------------------------------------------------------------------
# Adversarial (ambiguous borderline) samples — hand-crafted
# ---------------------------------------------------------------------------

def _adversarial_samples(rng: random.Random) -> List[Dict[str, Any]]:
    """~60 samples with ambiguous OS strings, mixed signals, edge resources."""
    samples: List[Dict[str, Any]] = []

    # Ambiguous / truncated OS names on Hyper-V (UNKNOWN path)
    for _ in range(15):
        samples.append(_make_sample(rng, "unknown",
                                     rng.choice(["", "linux?", "server", "generic-vm"]),
                                     "", "hyper_v",
                                     rng.randint(1, 4),
                                     rng.choice([768, 1024, 2048]),
                                     rng.randint(8, 50)))

    # KVM with disk=0 and otherwise reasonable specs
    for _ in range(10):
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        samples.append(_make_sample(rng, os_type, os_name, os_version, "kvm",
                                     rng.randint(2, 8),
                                     rng.choice([2048, 4096]), 0))

    # Edge resource values: exactly at thresholds
    for _ in range(10):
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        samples.append(_make_sample(rng, os_type, os_name, os_version, "kvm",
                                     1, rng.choice([511, 512, 1023, 1024]),
                                     rng.choice([9, 10, 11])))

    # VMware WS with VMDK format (partial path) but tiny memory (incompatible)
    for _ in range(10):
        os_type, os_name, os_version = rng.choice(_LINUX_SAMPLES)
        samples.append(_make_sample(rng, os_type, os_name, os_version,
                                     "vmware_workstation",
                                     rng.randint(1, 2),
                                     rng.randint(256, 510),
                                     rng.randint(20, 100)))

    # Unsupported Linux versions near the boundary
    boundary = [
        ("linux", "Ubuntu 17.10", "17.10"),
        ("linux", "Ubuntu 18.04", "18.04"),
        ("linux", "CentOS 6.10", "6.10"),
        ("linux", "CentOS 7.0", "7.0"),
        ("linux", "Debian 9", "9"),
        ("linux", "Debian 10", "10"),
    ]
    for entry in boundary:
        os_type, os_name, os_version = entry
        samples.append(_make_sample(rng, os_type, os_name, os_version, "kvm",
                                     2, 2048, 40))

    # Windows on KVM with convertible format (no — KVM defaults to qcow2, so this is compatible)
    for _ in range(5):
        os_type, os_name, os_version = rng.choice(_WINDOWS_SUPPORTED)
        samples.append(_make_sample(rng, os_type, os_name, os_version, "kvm",
                                     rng.randint(2, 4),
                                     rng.choice([4096, 8192]),
                                     rng.randint(40, 200)))

    return samples


# ---------------------------------------------------------------------------
# Labelling & noise
# ---------------------------------------------------------------------------

def _label(vm: Dict[str, Any]) -> str:
    """Derive the baseline grade via the rule engine."""
    return aggregate(evaluate_all(vm))["grade"]


def _apply_label_noise(
    labelled: List[Tuple[Dict[str, Any], str]],
    noise_ratio: float,
    rng: random.Random,
) -> List[Tuple[Dict[str, Any], str]]:
    n_flip = int(len(labelled) * noise_ratio)
    indices = rng.sample(range(len(labelled)), n_flip)
    neighbour = {
        "COMPATIBLE": "PARTIAL",
        "PARTIAL": rng.choice(["COMPATIBLE", "INCOMPATIBLE"]),
        "INCOMPATIBLE": "PARTIAL",
    }
    out = list(labelled)
    for i in indices:
        vm, grade = out[i]
        out[i] = (vm, neighbour[grade] if grade != "PARTIAL"
                  else rng.choice(["COMPATIBLE", "INCOMPATIBLE"]))
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_dataset(
    n_samples: int = 1800,
    noise_ratio: float = 0.07,
    seed: int = 42,
) -> List[Tuple[Dict[str, Any], str]]:
    """
    Generate a labelled synthetic dataset.

    Returns:
        List of (vm_dict, grade) tuples. ``grade`` is one of
        ``"COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE"``.
    """
    rng = random.Random(seed)

    n_compatible = int(n_samples * 0.40)
    n_partial = int(n_samples * 0.35)
    n_incompatible = n_samples - n_compatible - n_partial

    raw: List[Dict[str, Any]] = []
    for _ in range(n_compatible):
        raw.append(_gen_compatible(rng))
    for _ in range(n_partial):
        raw.append(_gen_partial(rng))
    for _ in range(n_incompatible):
        raw.append(_gen_incompatible(rng))

    raw.extend(_adversarial_samples(rng))

    labelled = [(vm, _label(vm)) for vm in raw]
    labelled = _apply_label_noise(labelled, noise_ratio, rng)
    rng.shuffle(labelled)
    return labelled


if __name__ == "__main__":
    data = generate_dataset()
    from collections import Counter
    counts = Counter(grade for _, grade in data)
    print(f"Total: {len(data)}")
    for grade, n in counts.most_common():
        print(f"  {grade}: {n} ({100*n/len(data):.1f} %)")
