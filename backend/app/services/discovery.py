"""
Discovery Service - Découverte des VMs depuis les hyperviseurs sources

Supporte :
- VMware vSphere (via pyvmomi)
- VMware Workstation (via vmrun)
- Hyper-V (via PowerShell)
- KVM/QEMU (via libvirt)
- Proxmox VE (via proxmoxer)
- oVirt / RHV (via ovirt-engine-sdk-python)
"""

import json
import os
import re
import subprocess
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging

from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus, OSType
from app.services.ovirt_rest import build_base_url, to_int

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Erreur lors de la découverte de VMs"""
    pass


# ============================================================================
# VMware Workstation helpers
# ============================================================================

# Default vmrun locations per platform
_VMRUN_CANDIDATES = [
    r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    "/usr/bin/vmrun",
    "/Applications/VMware Fusion.app/Contents/Library/vmrun",
]

# PowerShell script executed on the Hyper-V host to enumerate all VMs as JSON.
# Uses Get-VM (all power states) + Get-VHD for disk size.
_HYPERV_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'

function Get-ShiftwiseGuestOS($vm) {
    # Guest OS is only knowable host-side through the KVP Data Exchange
    # integration service (Msvm_KvpExchangeComponent.GuestIntrinsicExchangeItems).
    # Returns nulls when the guest's integration services are not running.
    # Never throws — discovery must not fail because OS info is unavailable.
    $info = [PSCustomObject]@{ name = $null; version = $null }
    try {
        $cs = Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_ComputerSystem -Filter "Name='$($vm.Id.Guid)'" -ErrorAction Stop
        $kvp = Get-CimAssociatedInstance -InputObject $cs -ResultClassName Msvm_KvpExchangeComponent -ErrorAction Stop
        foreach ($raw in $kvp.GuestIntrinsicExchangeItems) {
            if (-not $raw) { continue }
            $x = [xml]$raw
            $key = ($x.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Name' }).VALUE
            $val = ($x.INSTANCE.PROPERTY | Where-Object { $_.NAME -eq 'Data' }).VALUE
            if ($key -eq 'OSName')    { $info.name = $val }
            if ($key -eq 'OSVersion') { $info.version = $val }
        }
    } catch {}
    return $info
}

$vms = Get-VM
$result = foreach ($vm in $vms) {
    $net   = $vm.NetworkAdapters | Select-Object -First 1
    $ip    = if ($net -and $net.IPAddresses)  { $net.IPAddresses[0] }  else { $null }
    $mac   = if ($net -and $net.MacAddress)   { $net.MacAddress }       else { $null }

    $diskBytes = 0
    try {
        $diskBytes = ($vm.HardDrives | Get-VHD -ErrorAction SilentlyContinue |
                      Measure-Object -Property Size -Sum).Sum
    } catch {}

    $state = switch ($vm.State) {
        'Running' { 'running'  }
        'Off'     { 'stopped'  }
        'Paused'  { 'paused'   }
        default   { 'unknown'  }
    }

    $os = Get-ShiftwiseGuestOS $vm

    [PSCustomObject]@{
        name         = $vm.Name
        source_uuid  = ($vm.Id.ToString() -replace '-', '').ToLower()
        cpu_cores    = [int]$vm.ProcessorCount
        memory_mb    = [int]($vm.MemoryStartup / 1MB)
        disk_gb      = [int][Math]::Round($diskBytes / 1GB, 0)
        power_state  = $state
        ip_address   = $ip
        mac_address  = $mac
        hostname     = $vm.ComputerName
        generation   = [int]$vm.Generation
        os_name      = $os.name
        os_version   = $os.version
    }
}
$result | ConvertTo-Json -Depth 3
"""

# "efi" | "bios" — the guest boot firmware. Every connector populates a
# ``firmware`` key in its discovery dict so the migrator can emit the matching
# KubeVirt firmware block. A UEFI guest booted under KubeVirt's SeaBIOS default
# (or vice-versa) hangs at boot, so this must be detected per source.
_FW_EFI = "efi"
_FW_BIOS = "bios"
_FW_EFI_HINTS = ("efi", "ovmf", "uefi", "secure_boot")
_FW_BIOS_HINTS = ("bios", "seabios")


def _normalize_firmware(raw: Optional[Any]) -> Optional[str]:
    """Map a source-reported firmware hint to ``"efi"`` / ``"bios"`` / ``None``.

    ``None`` means the source did not report it — the migrator then keeps its
    SeaBIOS default. Accepts the various spellings connectors expose: VMware
    ``efi``/``bios``, Proxmox ``ovmf``/``seabios``, oVirt ``q35_ovmf`` /
    ``q35_secure_boot`` / ``q35_sea_bios``, libvirt ``pflash``/``efi``.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if any(h in s for h in _FW_EFI_HINTS):
        return _FW_EFI
    if any(h in s for h in _FW_BIOS_HINTS):
        return _FW_BIOS
    return None


# Remote wrapper: reads all sensitive values from env vars so that no credential
# ever appears in a command-line argument (prevents shell/PS injection).
_HYPERV_REMOTE_PS_WRAPPER = r"""
$pass = ConvertTo-SecureString $env:HV_PASS -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential($env:HV_USER, $pass)
$sb   = [scriptblock]::Create($env:HV_SCRIPT)
# -Authentication Negotiate: required for WinRM auth against a workgroup
# (non-domain) host with an explicit PSCredential. Without it WinRM falls
# back to a default that yields AccessDenied even with valid credentials.
Invoke-Command -ComputerName $env:HV_HOST -Credential $cred -Authentication Negotiate -ScriptBlock $sb
"""


def _find_vmrun() -> str:
    """
    Locate vmrun executable.

    Returns:
        Absolute path to vmrun.

    Raises:
        DiscoveryError: If vmrun cannot be found.
    """
    env_path = os.environ.get("VMRUN_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    for candidate in _VMRUN_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate

    raise DiscoveryError(
        "vmrun introuvable. Définissez la variable d'environnement VMRUN_PATH "
        "ou installez VMware Workstation / Fusion."
    )


def _run_vmrun(vmrun_path: str, *args, timeout: int = 30) -> str:
    """
    Execute a vmrun command and return stdout.

    Args:
        vmrun_path: Path to vmrun executable.
        *args:      Arguments passed to vmrun (e.g. '-T', 'ws', 'list').
        timeout:    Seconds before the call is killed.

    Returns:
        Stripped stdout string (may be empty).

    Raises:
        DiscoveryError: On non-zero exit or timeout.
    """
    cmd = [vmrun_path] + list(args)
    logger.debug(f"vmrun cmd: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise DiscoveryError(f"vmrun timeout ({timeout}s): {' '.join(cmd)}") from None
    except FileNotFoundError:
        raise DiscoveryError(f"vmrun introuvable à: {vmrun_path}") from None

    if result.returncode != 0:
        logger.debug(
            f"vmrun exited {result.returncode}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    return result.stdout.strip()


def _parse_vmx(vmx_path: str) -> Dict[str, str]:
    """
    Parse a .vmx file into a flat key→value dict.

    Keys are lowercased. Values have surrounding quotes stripped.

    Args:
        vmx_path: Absolute path to the .vmx file.

    Returns:
        Dict of configuration keys to their values.

    Raises:
        DiscoveryError: If the file cannot be read.
    """
    try:
        with open(vmx_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise DiscoveryError(f"Impossible de lire {vmx_path}: {exc}") from None

    config: Dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip().strip('"')
        config[key] = value

    return config


def _vmx_uuid(config: Dict[str, str]) -> str:
    """
    Extract a stable UUID string from parsed VMX config.

    Tries 'uuid.bios' first, then 'uuid.location'. Falls back to displayName.

    Returns:
        A normalised UUID-like string with no spaces or dashes.
    """
    raw = config.get("uuid.bios") or config.get("uuid.location") or ""
    if raw:
        return re.sub(r"[\s\-]", "", raw).lower()
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", config.get("displayname", "unknown"))


def _vmx_disk_gb(vmx_path: str, config: Dict[str, str]) -> int:
    """
    Estimate total disk size in GB by summing all VMDK files in the VMX directory.

    Uses os.listdir + os.path.getsize to enumerate ALL .vmdk files (descriptors,
    flat data files, snapshot chunks, growable extents).  Per-file errors are
    skipped so that a single permission issue does not zero-out the total.

    Returns:
        Total disk size in GB (minimum 1 when any VMDK exists), or 0.
    """
    vmx_dir = os.path.dirname(os.path.abspath(vmx_path))
    total_bytes: int = 0

    try:
        for entry in os.listdir(vmx_dir):
            if entry.lower().endswith(".vmdk"):
                filepath = os.path.join(vmx_dir, entry)
                try:
                    if os.path.isfile(filepath):
                        total_bytes += os.path.getsize(filepath)
                except OSError:
                    continue
    except OSError as e:
        logger.debug(f"Erreur listdir pour calcul taille disque: {e}")

    if total_bytes == 0:
        return 0

    disk_gb = round(total_bytes / 1_073_741_824)
    return max(1, disk_gb)


def _vmx_os_type(guest_os: str) -> OSType:
    # """Map VMX 'guestOS' value to our OSType enum."""
    # guest_os = guest_os.lower()

    # for kw in ["windows", "win", "longhorn", "vista", "server2"]:
    #     if kw in guest_os:
    #         return OSType.WINDOWS

    # for kw in [
    #     "ubuntu", "centos", "rhel", "fedora", "debian", "suse", "opensuse",
    #     "linux", "alpine", "arch", "gentoo", "oracle", "amazon", "coreos",
    #     "photon", "asianux",
    # ]:
    #     if kw in guest_os:
    #         return OSType.LINUX

    # if any(k in guest_os for k in ["freebsd", "netbsd", "openbsd", "darwin", "macos", "osx"]):
    #     return OSType.OTHER

    # return OSType.UNKNOWN
    """Map VMX 'guestOS' value to our OSType enum."""
    guest_os = guest_os.lower()

    # Check BSD/macOS FIRST, before Windows check (darwin contains "win")
    if any(k in guest_os for k in ["freebsd", "netbsd", "openbsd", "darwin", "macos", "osx"]):
        return OSType.OTHER

    for kw in ["windows", "win", "longhorn", "vista", "server2"]:
        if kw in guest_os:
            return OSType.WINDOWS

    for kw in [
        "ubuntu", "centos", "rhel", "fedora", "debian", "suse", "opensuse",
        "linux", "alpine", "arch", "gentoo", "oracle", "amazon", "coreos",
        "photon", "asianux",
    ]:
        if kw in guest_os:
            return OSType.LINUX

    return OSType.UNKNOWN


# ============================================================================
# vSphere / ESXi helpers
# ============================================================================
#
# The mapping helpers below are pure and getattr-based so they can be unit
# tested with plain objects standing in for pyVmomi managed objects — no live
# vCenter/ESXi and no ``pyVmomi`` import on the mapping path. Only the network
# boundary (``_vsphere_fetch_vms``) touches pyVmomi, and it is monkeypatched in
# tests. SmartConnect works against a standalone ESXi host directly.

# pyVmomi ``runtime.powerState`` -> our discovery power_state vocabulary.
_VSPHERE_POWER_MAP = {
    "poweredOn": "running",
    "poweredOff": "stopped",
    "suspended": "suspended",
}


def _vsphere_normalise_uuid(raw: Optional[str]) -> str:
    """Normalise a vSphere UUID to 32-char lowercase no-dash (KVM/oVirt style)."""
    return (raw or "").replace("-", "").lower()


def _vsphere_os_type(guest_full_name: Optional[str], guest_id: Optional[str]) -> OSType:
    """Classify a vSphere guest by its ``guestFullName`` / ``guestId``.

    Delegates to :func:`_vmx_os_type`, whose substring matching already covers
    the vSphere vocabulary (e.g. ``ubuntu64Guest`` contains ``ubuntu``).
    """
    combined = f"{guest_full_name or ''} {guest_id or ''}"
    return _vmx_os_type(combined)


def _vsphere_total_disk_gb(devices: Any) -> int:
    """Sum every virtual disk's capacity (GiB) from a device list.

    A device is treated as a disk when it carries ``capacityInKB`` /
    ``capacityInBytes`` — true only for ``VirtualDisk`` devices, so NICs and
    controllers are ignored without importing ``pyVmomi`` here.
    """
    total_kb = 0
    for dev in devices or []:
        cap_kb = getattr(dev, "capacityInKB", None)
        if cap_kb is None:
            cap_bytes = getattr(dev, "capacityInBytes", None)
            if not cap_bytes:
                continue
            cap_kb = int(cap_bytes) // 1024
        total_kb += int(cap_kb)
    return int(total_kb // (1024 * 1024))


def _vsphere_primary_mac(net_list: Any) -> Optional[str]:
    """First non-empty MAC from ``guest.net`` (only populated when tools run)."""
    for entry in net_list or []:
        mac = getattr(entry, "macAddress", None)
        if mac:
            return mac
    return None


def _vsphere_vm_to_dict(vm_obj: Any) -> Dict[str, Any]:
    """Map a pyVmomi ``VirtualMachine`` to a discovery dict.

    The result conforms to the contract consumed by ``_save_discovered_vms`` /
    ``_create_vm_from_discovery``: ``name``, ``source_uuid`` and ``source_name``
    are always present and non-empty; the rest are best-effort.
    """
    config = getattr(vm_obj, "config", None)
    guest = getattr(vm_obj, "guest", None)
    runtime = getattr(vm_obj, "runtime", None)
    hardware = getattr(config, "hardware", None)

    name = getattr(vm_obj, "name", None) or "unknown"
    uuid = _vsphere_normalise_uuid(
        getattr(config, "instanceUuid", None) or getattr(config, "uuid", None)
    )
    guest_full_name = (
        getattr(guest, "guestFullName", None)
        or getattr(config, "guestFullName", None)
    )
    guest_id = getattr(guest, "guestId", None) or getattr(config, "guestId", None)
    power_state = _VSPHERE_POWER_MAP.get(
        str(getattr(runtime, "powerState", "")), "unknown"
    )

    return {
        # source_uuid keys the DB sync and the converter's VM resolution; fall
        # back to the name only if the host exposes no UUID at all.
        "source_uuid": uuid or name,
        "source_name": name,
        "name": name,
        "cpu_cores": int(getattr(hardware, "numCPU", 0) or 0),
        "memory_mb": int(getattr(hardware, "memoryMB", 0) or 0),
        "disk_gb": _vsphere_total_disk_gb(getattr(hardware, "device", None)),
        "os_type": _vsphere_os_type(guest_full_name, guest_id),
        "os_version": guest_full_name,
        "os_name": guest_full_name,
        "ip_address": getattr(guest, "ipAddress", None),
        "mac_address": _vsphere_primary_mac(getattr(guest, "net", None)),
        "hostname": getattr(guest, "hostName", None),
        "power_state": power_state,
        # "efi" | "bios" — drives the KubeVirt firmware block at migration time.
        # A UEFI guest stalls under KubeVirt's SeaBIOS default (no legacy MBR
        # bootloader); the migrator emits an EFI bootloader when this is "efi".
        "firmware": getattr(config, "firmware", None),
    }


def _vsphere_fetch_vms(hypervisor: Hypervisor) -> List[Dict[str, Any]]:
    """Connect to vCenter/ESXi and return one discovery dict per VM.

    Network boundary — imports pyVmomi lazily so the rest of the module loads
    without the dependency, and so tests can monkeypatch this function.

    pyVmomi managed objects are lazy: reading a property issues a SOAP call on
    the live session. We therefore project each VM to a plain dict via
    :func:`_vsphere_vm_to_dict` **while the session is still open**, and never
    leak session-bound objects past ``Disconnect`` (doing so raises
    ``NotAuthenticated`` on the first property access).
    """
    import ssl

    from pyVim.connect import Disconnect, SmartConnect  # type: ignore
    from pyVmomi import vim  # type: ignore

    password = hypervisor.password_plain
    if not password:
        raise DiscoveryError(
            f"vSphere {hypervisor.host}: aucun identifiant utilisable"
        )

    if hypervisor.verify_ssl:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl._create_unverified_context()  # NOSONAR — self-signed ESXi dev

    si = SmartConnect(
        host=hypervisor.host,
        user=hypervisor.username,
        pwd=password,
        port=hypervisor.port or 443,
        sslContext=ctx,
    )
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            # Map while connected — the session must be live for every
            # lazy property access inside _vsphere_vm_to_dict.
            return [_vsphere_vm_to_dict(vm_obj) for vm_obj in view.view]
        finally:
            try:
                view.Destroy()
            except Exception:  # NOSONAR — best-effort cleanup
                logger.debug("vSphere view destroy failed", exc_info=True)
    finally:
        try:
            Disconnect(si)
        except Exception:  # NOSONAR — best-effort cleanup
            logger.debug("vSphere disconnect failed", exc_info=True)


def _vmx_os_version(guest_os: str) -> str:
    """Convert the raw guestOS string to a human-readable OS version label."""
    mapping = {
        "ubuntu": "Ubuntu Linux",
        "ubuntu-64": "Ubuntu Linux (64-bit)",
        "centos": "CentOS Linux",
        "centos-64": "CentOS Linux (64-bit)",
        "rhel": "Red Hat Enterprise Linux",
        "rhel7-64": "RHEL 7 (64-bit)",
        "rhel8-64": "RHEL 8 (64-bit)",
        "fedora": "Fedora Linux",
        "debian": "Debian Linux",
        "sles": "SUSE Linux Enterprise",
        "opensuse": "openSUSE",
        "windows9": "Windows 10",
        "windows9-64": "Windows 10 (64-bit)",
        "windows9srv-64": "Windows Server 2016/2019 (64-bit)",
        "windows2019srv-64": "Windows Server 2019 (64-bit)",
        "windows2022srvnext-64": "Windows Server 2022 (64-bit)",
        "darwin": "macOS",
    }
    normalised = guest_os.lower()
    for k, v in mapping.items():
        if normalised == k:
            return v
    return guest_os.capitalize()


def _get_running_vmx_paths(vmrun_path: str) -> List[str]:
    """Return list of VMX paths that are currently running via ``vmrun -T ws list``."""
    try:
        output = _run_vmrun(vmrun_path, "-T", "ws", "list")
    except DiscoveryError as exc:
        logger.warning(f"Impossible d'obtenir les VMs actives: {exc}")
        return []

    paths: List[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("total running"):
            continue
        if line:
            paths.append(line)

    return paths


def _get_tools_state(vmrun_path: str, vmx_path: str) -> str:
    """Return the VMware Tools state for a given VM."""
    try:
        output = _run_vmrun(vmrun_path, "-T", "ws", "checkToolsState", vmx_path, timeout=5)
        return output.strip().lower() if output else "unknown"
    except DiscoveryError:
        return "unknown"


def _get_vm_ip(vmrun_path: str, vmx_path: str) -> Optional[str]:
    """Try to get the IP address of a running VM via VMware Tools."""
    try:
        output = _run_vmrun(vmrun_path, "-T", "ws", "getGuestIPAddress", vmx_path, timeout=5)
        ip = output.strip()
        if ip and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
            return ip
    except DiscoveryError:
        pass
    return None


def _run_guest_script(
    vmrun_path: str,
    vmx_path: str,
    script: str,
    guest_credentials: Optional[Dict[str, str]] = None,
    timeout: int = 8,
) -> Optional[str]:
    """
    Execute a shell script inside a running guest via ``runScriptInGuest``.

    Tries with guest credentials first (required on some VMware Workstation
    versions), then falls back to running without credentials.

    Returns:
        Stripped stdout on success, ``None`` on failure.
    """
    attempts: List[list] = []

    if guest_credentials:
        attempts.append([
            "-T", "ws",
            "-gu", guest_credentials["username"],
            "-gp", guest_credentials["password"],
            "runScriptInGuest", vmx_path, "/bin/bash", script,
        ])

    # Try without credentials (works on newer VMware Workstation / Fusion)
    # (When creds were supplied but failed, retrying without them almost
    # always also fails or hangs — skip to avoid double-timeout cost.)
    if not guest_credentials:
        attempts.append([
            "-T", "ws",
            "runScriptInGuest", vmx_path, "/bin/bash", script,
        ])

    for args in attempts:
        try:
            cmd = [vmrun_path] + args
            logger.debug(f"runScriptInGuest cmd: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output:
                return output
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

    return None


def _vmrun_read_variable(vmrun_path: str, vmx_path: str, var_name: str, timeout: int = 5) -> Optional[str]:
    """
    Read a GuestInfo variable from a running VM using ``vmrun readVariable``.
    Does NOT require guest credentials. Returns None on any failure.
    """
    try:
        result = subprocess.run(
            [vmrun_path, "-T", "ws", "readVariable", vmx_path, "guestinfo", var_name],
            capture_output=True, text=True, timeout=timeout,
        )
        val = result.stdout.strip()
        if result.returncode == 0 and val:
            return val
    except Exception:
        pass
    return None

def _discover_single_vmx(
    vmrun_path: str,
    vmx_path: str,
    running_paths: List[str],
    guest_credentials: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build a VM discovery dict from a single .vmx file.

    Args:
        vmrun_path:       Path to vmrun executable.
        vmx_path:         Absolute path to the .vmx file.
        running_paths:    List of currently-running VMX paths (from vmrun list).
        guest_credentials: Optional dict with ``username`` / ``password`` keys
                           for authenticating ``runScriptInGuest`` calls.

    Returns:
        Dict compatible with _save_discovered_vms / _create_vm_from_discovery.
    """
    config = _parse_vmx(vmx_path)

    display_name = config.get("displayname") or Path(vmx_path).stem
    uuid = _vmx_uuid(config)
    num_cpus = int(config.get("numvcpus", config.get("cpuid.corespersocket", "1")))
    memory_mb = int(config.get("memsize", "1024"))
    disk_gb = _vmx_disk_gb(vmx_path, config)
    guest_os_raw = config.get("guestos", "other")
    os_type = _vmx_os_type(guest_os_raw)
    os_version = _vmx_os_version(guest_os_raw)
    os_name = f"{os_version} (guestOS={guest_os_raw})"
    mac_address = (
        config.get("ethernet0.generatedaddress")
        or config.get("ethernet0.address")
        or None
    )

    def _norm(p: str) -> str:
        return p.replace("\\", "/").lower()

    is_running = _norm(vmx_path) in [_norm(p) for p in running_paths]
    power_state = "running" if is_running else "poweredOff"

    ip_address: Optional[str] = None
    hostname_val: Optional[str] = None
    tools_state = "unknown"
    compatibility_status = CompatibilityStatus.UNKNOWN

    if is_running:
        tools_state = _get_tools_state(vmrun_path, vmx_path)
        if tools_state in ("installed", "running"):
            ip_address = _get_vm_ip(vmrun_path, vmx_path)

            if tools_state == "running":
                # Strategy 1: readVariable — no credentials needed, instant.
                # VMware Tools writes guestinfo variables that are readable
                # directly from the host without guest authentication.
                rv_hostname = _vmrun_read_variable(vmrun_path, vmx_path, "hostname")
                rv_os       = _vmrun_read_variable(vmrun_path, vmx_path, "os")
                rv_kernel   = _vmrun_read_variable(vmrun_path, vmx_path, "kernelVersion")

                if rv_hostname:
                    hostname_val = rv_hostname
                if rv_os:
                    os_name = rv_os
                if rv_kernel:
                    os_version = rv_kernel

                # Strategy 2: runScriptInGuest — only when guest credentials
                # are configured AND readVariable left some fields unfilled.
                # runScriptInGuest requires VMware Tools guest auth service to
                # be enabled inside the guest (disabled by default on Debian/
                # Ubuntu); without credentials it will hang until timeout.
                if guest_credentials:
                    if not hostname_val:
                        raw = _run_guest_script(
                            vmrun_path, vmx_path, "hostname",
                            guest_credentials=guest_credentials,
                        )
                        if raw:
                            hostname_val = raw
                    if os_version == _vmx_os_version(guest_os_raw):
                        raw = _run_guest_script(
                            vmrun_path, vmx_path, "uname -r",
                            guest_credentials=guest_credentials,
                        )
                        if raw:
                            os_version = raw
                    if os_name == f"{_vmx_os_version(guest_os_raw)} (guestOS={guest_os_raw})":
                        raw = _run_guest_script(
                            vmrun_path, vmx_path,
                            "grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'",
                            guest_credentials=guest_credentials,
                        )
                        if raw:
                            os_name = raw

            # Basic compatibility assessment: running VM with tools = compatible
            if os_type in (OSType.LINUX, OSType.WINDOWS):
                compatibility_status = CompatibilityStatus.COMPATIBLE
    else:
        tools_state = _get_tools_state(vmrun_path, vmx_path)
        # Powered-off VM with a supported OS type is still compatible
        if os_type in (OSType.LINUX, OSType.WINDOWS):
            compatibility_status = CompatibilityStatus.COMPATIBLE

    logger.info(
        f"  VMX '{display_name}': cpus={num_cpus}, mem={memory_mb}MB, "
        f"disk={disk_gb}GB, os={guest_os_raw!r}, "
        f"power={power_state}, tools={tools_state}, ip={ip_address}"
    )

    return {
        "source_uuid": uuid,
        "source_name": display_name,
        "name": display_name,
        "cpu_cores": num_cpus,
        "memory_mb": memory_mb,
        "disk_gb": disk_gb,
        "os_type": os_type,
        "os_version": os_version,
        "os_name": os_name,
        "ip_address": ip_address,
        "mac_address": mac_address,
        # VMX ``firmware = "efi"`` (absent ⇒ legacy BIOS).
        "firmware": _normalize_firmware(config.get("firmware")) or _FW_BIOS,
        "hostname": hostname_val,
        "power_state": power_state,
        "vmx_path": vmx_path,
        "tools_state": tools_state,
        "compatibility_status": compatibility_status,
    }


def _norm_path(p: str) -> str:
    """Normalise a filesystem path for case-insensitive comparison."""
    return p.replace("\\", "/").lower()


def _collect_extra_vmx_paths(hypervisor: Hypervisor) -> List[str]:
    """Read explicitly-registered extra VMX paths from the hypervisor record.

    Priority: ``additional_vmx_paths`` attribute → a JSON array in ``notes``
    → ``connection_config["extra_vmx_paths"]``. Returns an empty list on any
    parse error (a malformed override must never abort discovery).
    """
    extra_vmx: List[str] = []
    try:
        raw = getattr(hypervisor, "additional_vmx_paths", None) or ""
        if not raw:
            notes = getattr(hypervisor, "notes", None) or ""
            if notes.startswith("["):
                raw = notes
        if not raw:
            cfg = getattr(hypervisor, "connection_config", None) or {}
            paths = cfg.get("extra_vmx_paths", []) if isinstance(cfg, dict) else []
            extra_vmx = [str(p) for p in paths]
            raw = None
        if raw:
            extra_vmx = json.loads(raw)
    except Exception:  # NOSONAR — a bad override must not abort discovery
        return []
    return extra_vmx


def _resolve_vm_folder(cfg: Dict[str, Any]) -> Optional[str]:
    """Resolve the VMware Workstation VM folder to walk for .vmx files.

    Uses ``connection_config["vm_folder"]`` when present, otherwise probes
    the standard default locations. Returns ``None`` when none exist.
    """
    if isinstance(cfg, dict) and cfg.get("vm_folder"):
        return cfg["vm_folder"]

    default_vm_folders = [
        os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "Virtual Machines"),
        os.path.join(os.path.expanduser("~"), "Documents", "Virtual Machines"),
        os.path.join(os.path.expanduser("~"), "Virtual Machines"),
        "/var/lib/vmware/Virtual Machines",
    ]
    for candidate in default_vm_folders:
        if os.path.isdir(candidate):
            logger.info(f"vm_folder auto-détecté: {candidate}")
            return candidate
    return None


def _append_unique_vmx(target: List[str], candidate: str) -> None:
    """Append ``candidate`` to ``target`` unless an equivalent path is present."""
    norm = _norm_path(candidate)
    if not any(_norm_path(p) == norm for p in target):
        target.append(candidate)


def _collect_workstation_vmx_paths(
    hypervisor: Hypervisor, running_paths: List[str],
) -> List[str]:
    """Build the complete, de-duplicated set of VMX paths to inspect.

    Sources, in order: currently-running VMX paths, explicitly-registered
    extra paths, and a recursive walk of the configured VM folder. Extracted
    from ``_discover_vmware_workstation`` to keep its cognitive complexity
    below the SonarQube S3776 threshold — behaviour is unchanged.
    """
    vmx_paths_to_scan: List[str] = list(running_paths)

    for vmx in _collect_extra_vmx_paths(hypervisor):
        _append_unique_vmx(vmx_paths_to_scan, vmx)

    cfg = hypervisor.connection_config or {}
    vm_folder = _resolve_vm_folder(cfg)

    if vm_folder and os.path.isdir(vm_folder):
        logger.info(f"Scan du dossier VM: {vm_folder}")
        for root, _dirs, files in os.walk(vm_folder):
            for fname in files:
                if fname.lower().endswith(".vmx"):
                    full_path = os.path.join(root, fname)
                    if not any(
                        _norm_path(p) == _norm_path(full_path)
                        for p in vmx_paths_to_scan
                    ):
                        vmx_paths_to_scan.append(full_path)
                        logger.info(f"  VMX trouvé par scan dossier: {full_path}")
    elif not vmx_paths_to_scan:
        logger.warning(
            "Aucun VMX trouvé. Configurez 'vm_folder' dans connection_config "
            'ex: {"vm_folder": "C:\\\\Users\\\\PC\\\\Documents\\\\Virtual Machines"}'
        )

    return vmx_paths_to_scan


# ============================================================================
# KVM helpers
# ============================================================================

_KVM_STATE_MAP = {
    "running":     "running",
    "paused":      "paused",
    "shut off":    "stopped",
    "shutoff":     "stopped",
    "shutdown":    "stopped",
    "crashed":     "stopped",
    "pmsuspended": "paused",
}

_KVM_LINUX_KEYWORDS = [
    "linux", "ubuntu", "centos", "alpine", "debian",
    "fedora", "rhel", "suse", "arch", "gentoo",
]


def _parse_kvm_domain_xml(
    xml_str: str,
    state_str: str,
    disk_sizes: Dict[str, int],
) -> Dict[str, Any]:
    """Parse virsh dumpxml output into a ShiftWise VM dict."""
    root = ET.fromstring(xml_str)

    name = root.findtext("name") or "unknown"
    uuid_raw = root.findtext("uuid") or ""
    uuid = uuid_raw.replace("-", "").lower()

    cpu_cores = int(root.findtext("vcpu") or 1)
    memory_kb = int(root.findtext("memory") or 0)
    memory_mb = memory_kb // 1024

    disk_gb = 0
    for disk_el in root.findall(".//disk[@device='disk']"):
        src = disk_el.find("source")
        if src is not None:
            path = src.get("file") or src.get("dev") or ""
            if path and path in disk_sizes:
                disk_gb = max(disk_gb, disk_sizes[path])

    name_lower = name.lower()
    if any(k in name_lower for k in _KVM_LINUX_KEYWORDS):
        os_type = OSType.LINUX
    elif any(k in name_lower for k in ("windows", "win")):
        os_type = OSType.WINDOWS
    else:
        os_type = OSType.UNKNOWN

    power_state = _KVM_STATE_MAP.get(state_str.lower().strip(), "unknown")

    mac_address = None
    mac_el = root.find(".//interface/mac")
    if mac_el is not None:
        mac_address = mac_el.get("address")

    # Firmware: UEFI shows as <os firmware='efi'>, a <loader type='pflash'>,
    # or an <nvram> store; otherwise it is legacy BIOS.
    firmware = _FW_BIOS
    os_el = root.find("os")
    if os_el is not None:
        loader_el = os_el.find("loader")
        if (
            (os_el.get("firmware") or "").lower() == _FW_EFI
            or (loader_el is not None and (loader_el.get("type") or "").lower() == "pflash")
            or os_el.find("nvram") is not None
        ):
            firmware = _FW_EFI

    return {
        "source_uuid":          uuid,
        "source_name":          name,
        "name":                 name,
        "firmware":             firmware,
        "cpu_cores":            cpu_cores,
        "memory_mb":            memory_mb,
        "disk_gb":              disk_gb,
        "os_type":              os_type,
        "os_version":           "N/A",
        "os_name":              "N/A",
        "ip_address":           None,
        "mac_address":          mac_address,
        "hostname":             None,
        "power_state":          power_state,
        "compatibility_status": CompatibilityStatus.UNKNOWN,
    }


# ============================================================================
# Physical server (P2V) helpers
# ============================================================================

_PHYSICAL_DEV_PREFIX = "/dev/"


def _parse_lsblk_disks(lsblk_json: str, boot_source: str) -> List[Dict[str, Any]]:
    """Parse ``lsblk -b -J`` output into a list of disk descriptors.

    Only ``type == 'disk'`` devices are returned (rom/loop excluded). The disk
    whose partition tree contains ``boot_source`` (the device backing ``/``) is
    flagged ``is_boot`` and hoisted to index 0 — the converter treats index 0 as
    the bootable disk by convention.
    """
    data = json.loads(lsblk_json)
    boot_dev = boot_source.strip()

    def _contains_boot(node: Dict[str, Any]) -> bool:
        dev = f"{_PHYSICAL_DEV_PREFIX}{node.get('name', '')}"
        if dev == boot_dev:
            return True
        for child in node.get("children") or []:
            if f"{_PHYSICAL_DEV_PREFIX}{child.get('name', '')}" == boot_dev:
                return True
        return False

    disks: List[Dict[str, Any]] = []
    for node in data.get("blockdevices") or []:
        if node.get("type") != "disk":
            continue
        disks.append({
            "name": node.get("name", ""),
            "device": f"{_PHYSICAL_DEV_PREFIX}{node.get('name', '')}",
            "size_bytes": int(node.get("size") or 0),
            "is_boot": _contains_boot(node),
        })

    disks.sort(key=lambda d: (not d["is_boot"], d["name"]))
    return disks


def _build_physical_vm_dict(
    facts: Dict[str, Any],
    disks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble a ShiftWise VM dict for a physical host from collected facts.

    UUID strategy (stable, mirrors Proxmox/oVirt): DMI ``product_uuid`` →
    fallback synthetic ``physical-{hostname}``. The DMI UUID is normalised to
    32-char lowercase no-dash like the KVM/oVirt connectors.
    """
    hostname = (facts.get("hostname") or "unknown").strip()
    uuid_raw = (facts.get("uuid") or "").replace("-", "").lower().strip()
    source_uuid = uuid_raw if uuid_raw else f"physical-{hostname}"

    total_bytes = sum(int(d.get("size_bytes") or 0) for d in disks)
    disk_gb = max(0, -(-total_bytes // 1_073_741_824))  # ceil-div to GiB

    return {
        "source_uuid":          source_uuid,
        "source_name":          hostname,
        "name":                 hostname,
        "cpu_cores":            int(facts.get("cpu_cores") or 1),
        "memory_mb":            int(facts.get("memory_mb") or 0),
        "disk_gb":              disk_gb,
        "os_type":              OSType.LINUX,
        "os_version":           facts.get("os_version") or "N/A",
        "os_name":              facts.get("os_name") or "N/A",
        "ip_address":           facts.get("ip_address"),
        "mac_address":          facts.get("mac_address"),
        "hostname":             hostname,
        "firmware":             facts.get("firmware"),
        "power_state":          "running",
        "compatibility_status": CompatibilityStatus.UNKNOWN,
        # Per-disk capture plan consumed by PhysicalPuller.list_disks.
        "physical_disks":       disks,
    }


def _safe_int(value: str, *, default: int = 0) -> int:
    try:
        return int((value or "").strip())
    except (ValueError, TypeError):
        return default


def _grep_meminfo(line: str) -> int:
    """Extract the kB integer from a ``MemTotal:  8192000 kB`` line."""
    parts = (line or "").split()
    for token in parts:
        if token.isdigit():
            return int(token)
    return 0


def _parse_os_release(text: str) -> tuple:
    """Return (NAME, VERSION_ID) from /etc/os-release content."""
    name, version = "N/A", "N/A"
    for raw in (text or "").splitlines():
        if raw.startswith("NAME="):
            name = raw.split("=", 1)[1].strip().strip('"')
        elif raw.startswith("VERSION_ID="):
            version = raw.split("=", 1)[1].strip().strip('"')
    return name, version


def _parse_ip_json(ip_json: str) -> tuple:
    """Return (first non-loopback IPv4, its MAC) from ``ip -j addr`` output."""
    try:
        ifaces = json.loads(ip_json) if ip_json.strip() else []
    except (ValueError, TypeError):
        return None, None
    for iface in ifaces:
        if iface.get("ifname") == "lo":
            continue
        for addr in iface.get("addr_info") or []:
            local = addr.get("local")
            if local and not local.startswith("127."):
                return local, iface.get("address")
    return None, None


# ============================================================================
# Hyper-V helpers
# ============================================================================

# Audit A17 — un nom d'hôte/IP valide pour Invoke-Command : lettres,
# chiffres, points et tirets uniquement. Cela exclut tout métacaractère
# shell/PowerShell (`;` `|` `&` `` ` `` `$` espace, retour-ligne…) qui
# pourrait sortir du contexte `Invoke-Command -ComputerName $env:HV_HOST`.
_HYPERV_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_hyperv_host(host: str) -> str:
    """Valide le nom d'hôte Hyper-V distant (Audit A17).

    Le host est injecté dans `Invoke-Command -ComputerName`. Bien qu'il
    transite par une variable d'environnement (HV_HOST) et non par un
    argument de ligne de commande, on rejette tout caractère hors du jeu
    hostname/IP afin d'éliminer toute ambiguïté d'interprétation.

    Raises:
        DiscoveryError: Si le host est vide ou contient un caractère invalide.
    """
    h = (host or "").strip()
    if not h or not _HYPERV_HOSTNAME_RE.match(h):
        raise DiscoveryError(
            f"Nom d'hôte Hyper-V invalide: {host!r} — "
            "seuls les caractères [A-Za-z0-9._-] sont autorisés"
        )
    return h


def _build_hyperv_command(
    host: str,
    auth_mode: str,
    username: Optional[str],
    password: Optional[str],
) -> tuple:
    """
    Construit la commande PowerShell et les variables d'environnement pour la découverte Hyper-V.

    Returns:
        (cmd, extra_env) — extra_env is None for local, a dict of HV_* vars for remote.
    """
    is_local = (auth_mode == "local") and (host in ("localhost", "127.0.0.1"))
    if is_local:
        return ["powershell", "-NonInteractive", "-Command", _HYPERV_PS_SCRIPT], None

    if not username or not password:
        raise DiscoveryError(
            f"La découverte Hyper-V distante requiert username et password (host={host})"
        )
    # Audit A17 — valider le host avant de l'exposer à Invoke-Command.
    validated_host = _validate_hyperv_host(host)
    extra_env = {
        "HV_PASS":   password,
        "HV_USER":   username,
        "HV_HOST":   validated_host,
        "HV_SCRIPT": _HYPERV_PS_SCRIPT,
    }
    return ["powershell", "-NonInteractive", "-Command", _HYPERV_REMOTE_PS_WRAPPER], extra_env


_HYPERV_LINUX_OS_HINTS = (
    "linux", "ubuntu", "debian", "centos", "red hat", "redhat", "rhel",
    "suse", "fedora", "alpine", "rocky", "almalinux", "alma", "oracle linux",
    "gentoo", "arch",
)


def _hyperv_os_type(os_name: Optional[str]) -> OSType:
    """Classify the KVP-reported guest OS name into an ``OSType``.

    The Hyper-V KVP Data Exchange surfaces a free-form ``OSName`` (e.g.
    "Ubuntu 22.04.3 LTS", "Windows 10 Pro"). Returns ``UNKNOWN`` when the
    guest reported nothing (integration services not running).
    """
    if not os_name:
        return OSType.UNKNOWN
    s = os_name.lower()
    if "windows" in s:
        return OSType.WINDOWS
    if any(hint in s for hint in _HYPERV_LINUX_OS_HINTS):
        return OSType.LINUX
    return OSType.UNKNOWN


def _parse_hyperv_output(stdout: str) -> List[Dict[str, Any]]:
    """Parse la sortie JSON de PowerShell en liste de dicts VM standardisés."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"Impossible de parser la sortie JSON PowerShell: {exc}") from None

    # PowerShell emits a bare object (not array) when exactly one VM exists
    if isinstance(data, dict):
        data = [data]

    vms: List[Dict[str, Any]] = []
    for item in data:
        # Guest OS comes from the KVP Data Exchange service; absent when the
        # guest's integration services are down (os_name stays null → UNKNOWN).
        os_name = item.get("os_name")
        vms.append({
            "source_uuid":          item.get("source_uuid") or "",
            "source_name":          item.get("name") or "unknown",
            "name":                 item.get("name") or "unknown",
            "cpu_cores":            int(item.get("cpu_cores") or 0),
            "memory_mb":            int(item.get("memory_mb") or 0),
            "disk_gb":              int(item.get("disk_gb") or 0),
            "os_type":              _hyperv_os_type(os_name),
            "os_version":           item.get("os_version") or "N/A",
            "os_name":              os_name or "N/A",
            "ip_address":           item.get("ip_address"),
            "mac_address":          item.get("mac_address"),
            "hostname":             item.get("hostname"),
            "power_state":          item.get("power_state") or "unknown",
            "compatibility_status": CompatibilityStatus.UNKNOWN,
            # Hyper-V Generation 2 = UEFI, Generation 1 = legacy BIOS.
            "firmware": _FW_EFI if int(item.get("generation") or 1) >= 2 else _FW_BIOS,
        })
    return vms


# ============================================================================
# Proxmox VE helpers
# ============================================================================

_PROXMOX_STATE_MAP = {
    "running":   "running",
    "stopped":   "stopped",
    "paused":    "paused",
    "suspended": "paused",
}


def _proxmox_os_type(ostype: str) -> OSType:
    """Map a Proxmox ``ostype`` config shortcode to our OSType enum."""
    s = (ostype or "").lower()
    if s.startswith("w") or "win" in s:
        return OSType.WINDOWS
    if s in ("l24", "l26"):
        return OSType.LINUX
    if s in ("solaris", "other"):
        return OSType.OTHER
    return OSType.UNKNOWN


def _proxmox_os_version(ostype: str) -> str:
    """Human-readable version label from Proxmox ``ostype`` shortcodes."""
    mapping = {
        "l24":     "Linux 2.4",
        "l26":     "Linux 2.6+ / 3.x / 4.x / 5.x / 6.x",
        "win7":    "Windows 7",
        "win8":    "Windows 8",
        "win10":   "Windows 10",
        "win11":   "Windows 11",
        "w2k":     "Windows 2000",
        "w2k3":    "Windows Server 2003",
        "w2k8":    "Windows Server 2008",
        "wvista":  "Windows Vista",
        "wxp":     "Windows XP",
        "w2k16":   "Windows Server 2016",
        "w2k19":   "Windows Server 2019",
        "w2k22":   "Windows Server 2022",
        "solaris": "Solaris",
        "other":   "Other",
    }
    return mapping.get((ostype or "").lower(), ostype or "unknown")


def _proxmox_extract_uuid(smbios1: str) -> Optional[str]:
    """Extract the SMBIOS UUID from a Proxmox ``smbios1`` config string.

    smbios1 looks like: "uuid=abc-123-xyz,manufacturer=..."
    Returns a normalised lowercase UUID without dashes, or None if absent.
    """
    if not smbios1:
        return None
    for part in smbios1.split(","):
        key, _, value = part.partition("=")
        if key.strip().lower() == "uuid" and value.strip():
            return re.sub(r"[\s\-]", "", value.strip()).lower()
    return None


def _proxmox_iface_ipv4(iface: Dict[str, Any]) -> Optional[str]:
    """Return the first routable IPv4 of a guest-agent interface, or None."""
    for ipinfo in iface.get("ip-addresses") or []:
        if ipinfo.get("ip-address-type") != "ipv4":
            continue
        addr = ipinfo.get("ip-address") or ""
        if addr and not addr.startswith("127."):
            return addr
    return None


def _proxmox_agent_ipv4(
    agent_net: Optional[List[Dict[str, Any]]],
) -> Optional[str]:
    """Pick the first routable IPv4 from qemu-guest-agent interface data."""
    if not agent_net:
        return None
    for iface in agent_net:
        iface_name = (iface.get("name") or "").lower()
        if iface_name in ("lo", "loopback") or iface_name.startswith(("docker", "veth", "br-")):
            continue
        addr = _proxmox_iface_ipv4(iface)
        if addr:
            return addr
    return None


def _parse_proxmox_vm(
    resource: Dict[str, Any],
    config: Dict[str, Any],
    agent_net: Optional[List[Dict[str, Any]]] = None,
    agent_hostname: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a ShiftWise VM dict from Proxmox cluster resource + qemu config."""
    vmid = resource.get("vmid")
    node = resource.get("node", "unknown")
    name = resource.get("name") or f"vm-{vmid}"

    # UUID: prefer SMBIOS, fall back to a stable synthetic key.
    uuid = _proxmox_extract_uuid(config.get("smbios1", ""))
    if not uuid:
        uuid = f"proxmox-{node}-{vmid}".lower()

    ostype = config.get("ostype", "") or ""
    os_type = _proxmox_os_type(ostype)
    os_version = _proxmox_os_version(ostype)
    os_name = f"{os_version} (ostype={ostype})" if ostype else os_version

    cores = int(config.get("cores", 0) or 0)
    sockets = int(config.get("sockets", 1) or 1)
    if cores:
        cpu_cores = cores * sockets
    else:
        cpu_cores = int(resource.get("maxcpu") or 1)

    # config.memory is in MB; resource.maxmem is in bytes.
    memory_mb = int(config.get("memory") or 0)
    if not memory_mb and resource.get("maxmem"):
        memory_mb = int(resource["maxmem"]) // (1024 * 1024)

    disk_bytes = int(resource.get("maxdisk") or 0)
    disk_gb = round(disk_bytes / 1_073_741_824) if disk_bytes else 0
    if disk_bytes and disk_gb == 0:
        disk_gb = 1

    power_state = _PROXMOX_STATE_MAP.get(
        (resource.get("status") or "").lower(), "unknown"
    )

    mac_address: Optional[str] = None
    net0 = config.get("net0")
    if net0:
        mac_match = re.search(
            r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})", net0, flags=re.IGNORECASE
        )
        if mac_match:
            mac_address = mac_match.group(1).upper()

    # IP from qemu-guest-agent (only available on running VMs with agent installed).
    ip_address = _proxmox_agent_ipv4(agent_net)

    # Proxmox ``bios``: ``ovmf`` ⇒ UEFI, ``seabios`` / absent ⇒ legacy BIOS.
    firmware = _normalize_firmware(config.get("bios")) or _FW_BIOS

    return {
        "source_uuid":          uuid,
        "source_name":          name,
        "name":                 name,
        "firmware":             firmware,
        "cpu_cores":            cpu_cores,
        "memory_mb":            memory_mb,
        "disk_gb":              disk_gb,
        "os_type":              os_type,
        "os_version":           os_version,
        "os_name":              os_name,
        "ip_address":           ip_address,
        "mac_address":          mac_address,
        # Real guest OS hostname when the agent reports it; the Proxmox API
        # otherwise exposes no hostname (the config "name" is the inventory
        # label, not the guest hostname), so it stays null.
        "hostname":             agent_hostname,
        "power_state":          power_state,
        "compatibility_status": CompatibilityStatus.UNKNOWN,
    }


# ============================================================================
# oVirt / RHV helpers
# ============================================================================

_OVIRT_STATE_MAP = {
    "up":                  "running",
    "powering_up":         "running",
    "wait_for_launch":     "running",
    "reboot_in_progress":  "running",
    "restoring_state":     "running",
    "down":                "stopped",
    "powering_down":       "stopped",
    "suspended":           "paused",
    "paused":              "paused",
    "saving_state":        "paused",
    "not_responding":      "unknown",
    "unknown":             "unknown",
    "image_locked":        "unknown",
}


def _ovirt_os_type(os_type_str: str) -> OSType:
    """Map an oVirt ``vm.os.type`` value (e.g. 'rhel_8x64') to our OSType enum."""
    s = (os_type_str or "").lower()
    if "windows" in s or s.startswith("win"):
        return OSType.WINDOWS
    if any(k in s for k in (
        "rhel", "linux", "ubuntu", "centos", "fedora", "debian",
        "suse", "sles", "opensuse", "oracle", "rocky", "alma",
    )):
        return OSType.LINUX
    if s == "other":
        return OSType.OTHER
    return OSType.UNKNOWN


def _parse_ovirt_vm(
    vm: Any,
    disk_gb: int,
    devices: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Build a ShiftWise VM dict from an ovirt-engine-sdk Vm object."""
    uuid = (getattr(vm, "id", "") or "").replace("-", "").lower()
    name = getattr(vm, "name", None) or "unknown"

    cpu_cores = 1
    try:
        topo = vm.cpu.topology
        cpu_cores = int((topo.cores or 1) * (topo.sockets or 1) * (topo.threads or 1))
    except (AttributeError, TypeError):
        pass

    memory_mb = 0
    try:
        memory_mb = int(getattr(vm, "memory", 0) or 0) // (1024 * 1024)
    except (AttributeError, TypeError, ValueError):
        pass

    status_obj = getattr(vm, "status", None)
    status_str = getattr(status_obj, "value", None) or str(status_obj or "")
    power_state = _OVIRT_STATE_MAP.get(status_str.lower(), "unknown")

    os_type_raw = ""
    try:
        os_type_raw = getattr(vm.os, "type", "") or ""
    except AttributeError:
        pass
    os_type = _ovirt_os_type(os_type_raw)
    os_version = os_type_raw or "unknown"
    os_name = os_type_raw or "unknown"

    hostname = getattr(vm, "fqdn", None) or None

    # oVirt BIOS type: q35_ovmf / q35_secure_boot ⇒ UEFI, *_sea_bios ⇒ BIOS.
    # cluster_default is unknown here → leave None (migrator keeps SeaBIOS).
    bios_obj = getattr(vm, "bios", None)
    bios_type = None
    if bios_obj is not None:
        t = getattr(bios_obj, "type", None)
        bios_type = getattr(t, "value", None) or (str(t) if t else None)
    firmware = _normalize_firmware(bios_type)

    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    for dev in devices or []:
        mac_obj = getattr(dev, "mac", None)
        if mac_obj and not mac_address:
            mac_address = getattr(mac_obj, "address", None)
        for ip in getattr(dev, "ips", None) or []:
            addr = getattr(ip, "address", None)
            version_obj = getattr(ip, "version", None)
            version = getattr(version_obj, "value", None) or str(version_obj or "")
            if addr and version.lower() in ("v4", "ipv4", "") and not addr.startswith("127."):
                ip_address = addr
                break
        if ip_address:
            break

    return {
        "source_uuid":          uuid,
        "source_name":          name,
        "name":                 name,
        "firmware":             firmware,
        "cpu_cores":            cpu_cores,
        "memory_mb":            memory_mb,
        "disk_gb":              disk_gb,
        "os_type":              os_type,
        "os_version":           os_version,
        "os_name":              os_name,
        "ip_address":           ip_address,
        "mac_address":          mac_address,
        "hostname":             hostname,
        "power_state":          power_state,
        "compatibility_status": CompatibilityStatus.UNKNOWN,
    }


def _ovirt_rest_first_ipv4(devices: Optional[List[dict]]) -> tuple[Optional[str], Optional[str]]:
    """Pull the first non-loopback IPv4 + MAC from oVirt reported-device JSON.

    oVirt nests addresses as ``{"ips": {"ip": [{"address": ..., "version": ...}]}}``
    on a running guest with the agent up; on older payloads ``ips`` may already be
    a list. Both shapes are handled.
    """
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    for dev in devices or []:
        mac = (dev.get("mac") or {}).get("address")
        if mac and not mac_address:
            mac_address = mac
        ips = dev.get("ips")
        ip_list = ips.get("ip") if isinstance(ips, dict) else ips
        for ip in ip_list or []:
            addr = ip.get("address")
            version = str(ip.get("version") or "")
            if addr and version.lower() in ("v4", "ipv4", "") and not addr.startswith("127."):
                ip_address = addr
                break
        if ip_address:
            break
    return ip_address, mac_address


def _parse_ovirt_vm_rest(
    vm: dict,
    disk_gb: int,
    devices: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Build a ShiftWise VM dict from an oVirt REST VM JSON object.

    Mirrors :func:`_parse_ovirt_vm` (the SDK-object variant) but reads JSON dicts
    and coerces oVirt's stringly-typed numerics via :func:`to_int`.
    """
    uuid = (vm.get("id") or "").replace("-", "").lower()
    name = vm.get("name") or "unknown"

    topo = (vm.get("cpu") or {}).get("topology") or {}
    cpu_cores = (
        to_int(topo.get("cores"), 1)
        * to_int(topo.get("sockets"), 1)
        * to_int(topo.get("threads"), 1)
    ) or 1

    memory_mb = to_int(vm.get("memory"), 0) // (1024 * 1024)

    status_str = str(vm.get("status") or "").lower()
    power_state = _OVIRT_STATE_MAP.get(status_str, "unknown")

    os_type_raw = (vm.get("os") or {}).get("type") or ""
    os_type = _ovirt_os_type(os_type_raw)

    bios_type = (vm.get("bios") or {}).get("type")
    firmware = _normalize_firmware(bios_type)

    hostname = vm.get("fqdn") or None
    ip_address, mac_address = _ovirt_rest_first_ipv4(devices)

    return {
        "source_uuid":          uuid,
        "source_name":          name,
        "name":                 name,
        "firmware":             firmware,
        "cpu_cores":            cpu_cores,
        "memory_mb":            memory_mb,
        "disk_gb":              disk_gb,
        "os_type":              os_type,
        "os_version":           os_type_raw or "unknown",
        "os_name":              os_type_raw or "unknown",
        "ip_address":           ip_address,
        "mac_address":          mac_address,
        "hostname":             hostname,
        "power_state":          power_state,
        "compatibility_status": CompatibilityStatus.UNKNOWN,
    }


class DiscoveryService:
    """Service de découverte des VMs depuis les hyperviseurs"""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # MÉTHODES PRINCIPALES
    # ========================================================================

    def discover_hypervisor(self, hypervisor_id: int) -> Dict[str, Any]:
        """
        Découvre toutes les VMs d'un hypervisor et synchronise la base de données.

        Args:
            hypervisor_id: ID de l'hypervisor à scanner.

        Returns:
            Statistiques de découverte.

        Raises:
            DiscoveryError: Si la découverte échoue.
        """
        hypervisor = self.db.query(Hypervisor).filter(
            Hypervisor.id == hypervisor_id
        ).first()

        if not hypervisor:
            raise DiscoveryError(f"Hypervisor {hypervisor_id} introuvable")

        logger.info(f"Début découverte hypervisor {hypervisor.name} (type: {hypervisor.type})")

        hypervisor.status = HypervisorStatus.DISCOVERING
        self.db.commit()

        try:
            if hypervisor.type in (HypervisorType.VSPHERE, HypervisorType.VMWARE_ESXi):
                vms_data = self._discover_vsphere(hypervisor)
            elif hypervisor.type == HypervisorType.VMWARE_WORKSTATION:
                vms_data = self._discover_vmware_workstation(hypervisor)
            elif hypervisor.type == HypervisorType.HYPER_V:
                vms_data = self._discover_hyperv(hypervisor)
            elif hypervisor.type == HypervisorType.KVM:
                vms_data = self._discover_kvm(hypervisor)
            elif hypervisor.type == HypervisorType.PROXMOX:
                vms_data = self._discover_proxmox(hypervisor)
            elif hypervisor.type == HypervisorType.OVIRT:
                vms_data = self._discover_ovirt(hypervisor)
            elif hypervisor.type == HypervisorType.PHYSICAL:
                vms_data = self._discover_physical(hypervisor)
            else:
                raise DiscoveryError(f"Type d'hypervisor non supporté: {hypervisor.type}")

            stats = self._save_discovered_vms(hypervisor, vms_data)

            hypervisor.update_status(HypervisorStatus.ACTIVE)
            self.db.commit()

            logger.info(f"Découverte terminée: {stats['total_discovered']} VMs trouvées")
            return stats

        except (DiscoveryError, ConnectionError, TimeoutError) as e:
            logger.error(f"Erreur découverte hypervisor {hypervisor.name}: {str(e)}")
            hypervisor.update_status(HypervisorStatus.ERROR, error_message=str(e))
            hypervisor.mark_sync_completed(success=False)
            self.db.commit()
            raise DiscoveryError(f"Échec de la découverte: {str(e)}") from None

        except Exception as e:  # NOSONAR — voir Audit E5 ci-dessous
            # Audit E5 — toute exception non classifiée (driver tiers, bug,
            # erreur inattendue) doit AUSSI sortir l'hyperviseur de l'état
            # DISCOVERING. DISCOVERING signifie « sync en cours » : laisser
            # cet état figé bloquerait toute synchronisation ultérieure.
            # On marque ERROR puis on relaie l'exception d'origine.
            logger.error(
                f"Erreur inattendue découverte hypervisor {hypervisor.name}: {e}",
                exc_info=True,
            )
            try:
                hypervisor.update_status(
                    HypervisorStatus.ERROR, error_message=str(e),
                )
                hypervisor.mark_sync_completed(success=False)
                self.db.commit()
            except Exception as reset_err:  # NOSONAR — best-effort reset
                logger.error(
                    "Échec de la remise à zéro du statut hypervisor "
                    f"{hypervisor.name}: {reset_err}"
                )
            raise

    def test_connection(self, hypervisor: Hypervisor) -> Dict[str, Any]:
        """Probe a hypervisor's reachability and credentials without persisting.

        Reuses the per-type _discover_* methods but stops after the VM
        enumeration step — nothing is written to the database. Returns a
        dict with `success` (bool), `vms_count` (int|None) and `error`
        (str|None).
        """
        try:
            if hypervisor.type in (HypervisorType.VSPHERE, HypervisorType.VMWARE_ESXi):
                vms = self._discover_vsphere(hypervisor)
            elif hypervisor.type == HypervisorType.VMWARE_WORKSTATION:
                vms = self._discover_vmware_workstation(hypervisor)
            elif hypervisor.type == HypervisorType.HYPER_V:
                vms = self._discover_hyperv(hypervisor)
            elif hypervisor.type == HypervisorType.KVM:
                vms = self._discover_kvm(hypervisor)
            elif hypervisor.type == HypervisorType.PROXMOX:
                vms = self._discover_proxmox(hypervisor)
            elif hypervisor.type == HypervisorType.OVIRT:
                vms = self._discover_ovirt(hypervisor)
            elif hypervisor.type == HypervisorType.PHYSICAL:
                vms = self._discover_physical(hypervisor)
            else:
                return {
                    "success": False,
                    "vms_count": None,
                    "error": f"Unsupported hypervisor type: {hypervisor.type}",
                }
        except DiscoveryError as e:
            return {"success": False, "vms_count": None, "error": str(e)}
        except (ConnectionError, TimeoutError, OSError) as e:
            return {"success": False, "vms_count": None, "error": str(e)}

        return {"success": True, "vms_count": len(vms), "error": None}

    # ========================================================================
    # DÉCOUVERTE PAR TYPE D'HYPERVISOR
    # ========================================================================

    def _discover_vsphere(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Découvre les VMs depuis vCenter/ESXi via pyVmomi.

        Connecte l'endpoint (``SmartConnect`` fonctionne directement sur un hôte
        ESXi autonome), énumère toutes les ``VirtualMachine`` et les projette
        dans le contrat de découverte via :func:`_vsphere_vm_to_dict`. La
        résolution disque côté Converter s'appuie sur ``source_uuid``
        (instanceUuid normalisé) — d'où l'usage de la même normalisation ici.
        """
        logger.info(f"Découverte vSphere/ESXi: {hypervisor.host}")
        try:
            return _vsphere_fetch_vms(hypervisor)
        except ImportError as e:
            raise DiscoveryError(
                "pyvmomi non installé dans l'environnement worker"
            ) from e
        except DiscoveryError:
            raise
        except Exception as e:  # NOSONAR — pyVmomi lève des types variés
            raise DiscoveryError(f"Erreur connexion vSphere: {e}") from None

    def _discover_vmware_workstation(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """
        Découvre les VMs depuis VMware Workstation via vmrun + lecture des .vmx.

        Strategy
        --------
        1. Locate vmrun executable (env var → hypervisor.host → known install paths).
        2. Call ``vmrun -T ws list`` to get currently-running VMX paths.
        3. Collect the complete set of VMX files to inspect:
             a. Every running VMX path from step 2.
             b. Any extra VMX paths from ``hypervisor.connection_config["extra_vmx_paths"]``
                (covers powered-off VMs explicitly registered by the user).
        4. Parse each .vmx file and query live data (IP, tools state).
        5. Return the list — _save_discovered_vms handles all DB sync.

        Args:
            hypervisor: Hypervisor instance of type VMWARE_WORKSTATION.

        Returns:
            List of VM dicts ready for _save_discovered_vms.
        """
        logger.info("Découverte VMware Workstation (vmrun réel)")

        # ------------------------------------------------------------------ #
        # 1. Locate vmrun
        # ------------------------------------------------------------------ #
        if hypervisor.host and os.path.isfile(hypervisor.host):
            vmrun_path = hypervisor.host
            logger.info(f"vmrun depuis hypervisor.host: {vmrun_path}")
        else:
            vmrun_path = _find_vmrun()
            logger.info(f"vmrun auto-détecté: {vmrun_path}")

        # ------------------------------------------------------------------ #
        # 2. Get currently running VMX paths
        # ------------------------------------------------------------------ #
        running_paths = _get_running_vmx_paths(vmrun_path)
        logger.info(f"VMs en cours d'exécution: {len(running_paths)}")
        for p in running_paths:
            logger.info(f"  - {p}")

        # ------------------------------------------------------------------ #
        # 3. Build complete set of VMX paths to inspect (running + extra +
        #    directory scan). Delegated to a helper — Audit S3776.
        # ------------------------------------------------------------------ #
        vmx_paths_to_scan = _collect_workstation_vmx_paths(hypervisor, running_paths)

        # ------------------------------------------------------------------ #
        # 4. Extract optional guest credentials for runScriptInGuest
        # ------------------------------------------------------------------ #
        guest_creds: Optional[Dict[str, str]] = None
        cfg = hypervisor.connection_config or {}
        if isinstance(cfg, dict) and cfg.get("guest_username"):
            guest_creds = {
                "username": cfg["guest_username"],
                "password": cfg.get("guest_password", ""),
            }

        # ------------------------------------------------------------------ #
        # 5 & 6. Parse each VMX and gather live data
        # ------------------------------------------------------------------ #
        vms_data: List[Dict[str, Any]] = []

        for vmx_path in vmx_paths_to_scan:
            try:
                vm_dict = _discover_single_vmx(
                    vmrun_path, vmx_path, running_paths,
                    guest_credentials=guest_creds,
                )
                vms_data.append(vm_dict)
                logger.info(f"✅ Découvert: {vm_dict['name']} ({vm_dict['power_state']})")
            except DiscoveryError as exc:
                logger.error(f"❌ Échec scan VMX {vmx_path}: {exc}")
            except Exception as exc:
                logger.error(f"❌ Erreur inattendue VMX {vmx_path}: {exc}")
                logger.error(traceback.format_exc())

        return vms_data

    def _discover_hyperv(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Découvre les VMs d'un hôte Hyper-V via un script PowerShell."""
        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        host: str = hypervisor.host or "localhost"
        auth_mode: str = cfg.get("auth_mode", "local")

        logger.info(f"Découverte Hyper-V: host={host}, auth_mode={auth_mode}")

        cmd, extra_env = _build_hyperv_command(
            host, auth_mode, hypervisor.username, hypervisor.password_plain
        )

        run_env = None
        if extra_env:
            logger.warning(f"Connexion Hyper-V distante vers {host} (credentials utilisés, non journalisés)")
            run_env = {**os.environ, **extra_env}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=run_env,
            )
        except FileNotFoundError:
            raise DiscoveryError(
                "powershell.exe introuvable. La découverte Hyper-V nécessite Windows avec PowerShell."
            ) from None
        except subprocess.TimeoutExpired:
            raise DiscoveryError(
                f"PowerShell timeout (120s) lors de la découverte Hyper-V id={hypervisor.id}"
            ) from None

        if result.returncode != 0:
            raise DiscoveryError(
                f"Erreur PowerShell (rc={result.returncode}): {result.stderr.strip()}"
            )

        raw = result.stdout.strip()
        if not raw:
            logger.info("PowerShell: aucune VM retournée — retour liste vide (déclenche ARCHIVE)")
            return []

        vms = _parse_hyperv_output(raw)
        for vm in vms:
            logger.info(
                f"  Hyper-V '{vm['name']}': cpus={vm['cpu_cores']}, "
                f"mem={vm['memory_mb']}MB, disk={vm['disk_gb']}GB, "
                f"power={vm['power_state']}, ip={vm['ip_address']}"
            )
        return vms

    @staticmethod
    def _kvm_disk_sizes(run, disk_paths: List[str]) -> Dict[str, int]:
        """Return {disk_path: virtual-size GiB} via qemu-img on the SSH host."""
        disk_sizes: Dict[str, int] = {}
        for path in disk_paths:
            img_out, _, img_rc = run(
                f"qemu-img info --output=json '{path}' 2>/dev/null",
            )
            if img_rc != 0 or not img_out:
                continue
            try:
                vsize = json.loads(img_out).get("virtual-size", 0)
                disk_sizes[path] = max(1, round(vsize / 1_073_741_824))
            except (ValueError, KeyError):
                disk_sizes[path] = 0
        return disk_sizes

    @staticmethod
    def _kvm_disk_paths(root_el: "ET.Element") -> List[str]:
        """Extract disk source paths from a parsed libvirt domain XML tree."""
        disk_paths: List[str] = []
        for disk_el in root_el.findall(".//disk[@device='disk']"):
            src = disk_el.find("source")
            if src is None:
                continue
            path = src.get("file") or src.get("dev") or ""
            if path:
                disk_paths.append(path)
        return disk_paths

    def _kvm_collect_domain(self, run, name: str, safe_name: str) -> Optional[Dict[str, Any]]:
        """Discover a single KVM domain. Returns the VM dict or None on error.

        ``safe_name`` is the shell-quoted form of ``name`` (see ``_discover_kvm``)
        — it is the only value interpolated into a remote virsh command.
        """
        virsh = "virsh --connect qemu:///system"
        xml_out, xml_err, xml_rc = run(f"{virsh} dumpxml {safe_name}")
        if xml_rc != 0:
            logger.error(f"KVM dumpxml failed for '{name}': {xml_err}")
            return None

        state_out, _, _ = run(f"{virsh} domstate {safe_name}")
        state_str = state_out.strip()

        root_el = ET.fromstring(xml_out)
        disk_paths = self._kvm_disk_paths(root_el)
        disk_sizes = self._kvm_disk_sizes(run, disk_paths)

        vm_dict = _parse_kvm_domain_xml(xml_out, state_str, disk_sizes)

        # Best-effort live network/hostname via the QEMU guest agent. Only a
        # running domain with the agent installed answers; failures are silent
        # (a powered-off VM or a guest without qemu-guest-agent legitimately
        # exposes neither). virsh XML carries no IP/hostname, so without this
        # both fields stay null on every KVM VM.
        if vm_dict["power_state"] == "running":
            ip_addr = self._kvm_guest_ipv4(run, safe_name)
            if ip_addr:
                vm_dict["ip_address"] = ip_addr
            hostname = self._kvm_guest_hostname(run, safe_name)
            if hostname:
                vm_dict["hostname"] = hostname

        logger.info(
            f"  KVM '{vm_dict['name']}': cpus={vm_dict['cpu_cores']}, "
            f"mem={vm_dict['memory_mb']}MB, power={vm_dict['power_state']}, "
            f"disk={vm_dict['disk_gb']}GB, uuid={vm_dict['source_uuid']}, "
            f"ip={vm_dict['ip_address']}"
        )
        return vm_dict

    @staticmethod
    def _kvm_guest_ipv4(run, safe_name: str) -> Optional[str]:
        """First non-loopback IPv4 from ``virsh domifaddr`` (agent then lease).

        Returns None when neither source answers (guest agent absent, no DHCP
        lease yet). Parses the tabular ``Name MAC Protocol Address`` output,
        skipping loopback addresses.
        """
        virsh = "virsh --connect qemu:///system"
        for source in ("agent", "lease"):
            out, _, rc = run(f"{virsh} domifaddr {safe_name} --source {source} 2>/dev/null")
            if rc != 0 or not out:
                continue
            for line in out.splitlines():
                parts = line.split()
                # Address column is "ip/prefix"; protocol column reads "ipv4".
                if len(parts) >= 4 and parts[2].lower() == "ipv4":
                    addr = parts[3].split("/")[0]
                    if addr and not addr.startswith("127."):
                        return addr
        return None

    @staticmethod
    def _kvm_guest_hostname(run, safe_name: str) -> Optional[str]:
        """Guest OS hostname via the QEMU guest agent, or None when unavailable."""
        virsh = "virsh --connect qemu:///system"
        cmd = (
            f"{virsh} qemu-agent-command {safe_name} "
            f"'{{\"execute\":\"guest-get-host-name\"}}' 2>/dev/null"
        )
        out, _, rc = run(cmd)
        if rc != 0 or not out:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        hostname = (data.get("return") or {}).get("host-name")
        return hostname or None

    def _discover_kvm(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover KVM/QEMU VMs via SSH + virsh using paramiko.

        connection_config keys:
          auth_mode     — "ssh_key" (default) | "local" (qemu:///system, no SSH)
          ssh_key_path  — path to the private key. Falls back to
                          settings.KVM_SSH_KEY_PATH, then to the SSH agent /
                          ~/.ssh (look_for_keys). Audit S8392 — no hardcoded
                          developer key path in source.
        """
        import shlex
        import warnings as _warnings
        import paramiko
        from app.core.config import settings
        from app.core.ssh import apply_host_key_policy

        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        host_uri: str = hypervisor.host or "qemu:///system"

        ssh_match = re.match(r"qemu\+ssh://(?:([^@]+)@)?([^/?]+)", host_uri)
        if not ssh_match:
            raise DiscoveryError(
                f"KVM URI non supportée (attendu qemu+ssh://user@host/system): {host_uri}"
            )

        ssh_user: str = ssh_match.group(1) or "root"
        ssh_host: str = ssh_match.group(2)
        # Audit S8392 — le chemin de clé SSH vient de connection_config puis
        # de settings.KVM_SSH_KEY_PATH ; jamais codé en dur. Vide => paramiko
        # tombe sur l'agent / ~/.ssh via look_for_keys=True.
        ssh_key_path: Optional[str] = (
            cfg.get("ssh_key_path") or settings.KVM_SSH_KEY_PATH or None
        )

        logger.info(f"KVM SSH: {ssh_user}@{ssh_host}, key={ssh_key_path or '<agent/default>'}")

        def _run(cmd: str):
            _, stdout, stderr = client.exec_command(cmd)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return out, err, rc

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            client = paramiko.SSHClient()
            apply_host_key_policy(client)  # Audit H-02 — vérifie les clés d'hôte SSH
            try:
                client.connect(
                    ssh_host,
                    username=ssh_user,
                    key_filename=ssh_key_path,
                    timeout=15,
                    look_for_keys=True,
                )
            except Exception as exc:
                # Audit E8 — fermer le client si connect() échoue, sinon le
                # transport paramiko (et son thread) fuit jusqu'au GC.
                client.close()
                raise DiscoveryError(f"SSH KVM connection failed ({ssh_user}@{ssh_host}): {exc}") from None

        try:
            names_out, names_err, names_rc = _run("virsh --connect qemu:///system list --all --name")
            if names_rc != 0:
                raise DiscoveryError(f"virsh list failed: {names_err}")

            domain_names = [n for n in names_out.splitlines() if n.strip()]
            if not domain_names:
                logger.info("KVM: no domains found")
                return []

            vms: List[Dict[str, Any]] = []
            for name in domain_names:
                try:
                    # Audit A19 — le nom de domaine vient du serveur distant ;
                    # il est shell-quoté avant toute interpolation dans une
                    # commande virsh exécutée par le shell SSH distant.
                    safe_name = shlex.quote(name)
                    vm_dict = self._kvm_collect_domain(_run, name, safe_name)
                    if vm_dict is not None:
                        vms.append(vm_dict)
                except ET.ParseError as exc:
                    logger.error(f"KVM XML parse error for '{name}': {exc}")
                except Exception as exc:
                    logger.error(f"KVM error processing domain '{name}': {exc}")

            return vms
        finally:
            client.close()

    def _discover_proxmox(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover VMs from a Proxmox VE cluster via the ``proxmoxer`` library.

        connection_config keys (all optional):
          auth_method  — "password" (default) | "token"
          realm        — PVE realm (default: "pam")
          token_name   — API token name (required when auth_method == "token")
          token_value  — API token value (falls back to hypervisor.password_plain)
          port         — API port (default: 8006)
          node_filter  — list of node names to restrict discovery to
        """
        try:
            from proxmoxer import ProxmoxAPI
        except ImportError as exc:
            raise DiscoveryError(
                f"proxmoxer n'est pas installé: {exc}. "
                "Ajoutez 'proxmoxer' à requirements.txt."
            ) from None

        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        host: str = hypervisor.host or "localhost"
        port: int = int(hypervisor.port or cfg.get("port") or 8006)
        realm: str = cfg.get("realm") or "pam"
        auth_method: str = (cfg.get("auth_method") or "password").lower()
        node_filter = cfg.get("node_filter") or None

        user = hypervisor.username or "root"
        if "@" not in user:
            user = f"{user}@{realm}"

        logger.info(f"Proxmox: host={host}:{port}, user={user}, auth={auth_method}")

        try:
            if auth_method == "token":
                token_name = cfg.get("token_name") or ""
                token_value = cfg.get("token_value") or hypervisor.password_plain or ""
                if not token_name or not token_value:
                    raise DiscoveryError(
                        "Authentification par token Proxmox requiert 'token_name' "
                        "dans connection_config et une valeur de token "
                        "('token_value' ou hypervisor.password_plain)."
                    )
                proxmox = ProxmoxAPI(
                    host,
                    user=user,
                    token_name=token_name,
                    token_value=token_value,
                    port=port,
                    verify_ssl=bool(hypervisor.verify_ssl),
                    timeout=30,
                )
            else:
                proxmox = ProxmoxAPI(
                    host,
                    user=user,
                    password=hypervisor.password_plain or "",
                    port=port,
                    verify_ssl=bool(hypervisor.verify_ssl),
                    timeout=30,
                )
        except Exception as exc:
            raise DiscoveryError(f"Proxmox: échec de connexion à {host}: {exc}") from None

        try:
            resources = proxmox.cluster.resources.get(type="vm")
        except Exception as exc:
            raise DiscoveryError(f"Proxmox: cluster/resources a échoué: {exc}") from None

        # Restrict to QEMU (KVM) VMs — LXC containers are not yet supported.
        qemu_resources = [
            r for r in resources
            if r.get("type") == "qemu"
            and (not node_filter or r.get("node") in node_filter)
        ]

        if not qemu_resources:
            logger.info("Proxmox: aucune VM QEMU trouvée — retour liste vide (déclenche ARCHIVE)")
            return []

        vms: List[Dict[str, Any]] = []
        for resource in qemu_resources:
            node = resource.get("node")
            vmid = resource.get("vmid")
            if not node or vmid is None:
                continue
            vm_dict = self._proxmox_collect_vm(proxmox, resource, node, vmid)
            if vm_dict is not None:
                vms.append(vm_dict)
        return vms

    @staticmethod
    def _proxmox_agent_net(proxmox, resource, node, vmid) -> Optional[List[Dict[str, Any]]]:
        """Return guest-agent network interfaces, or None when unavailable."""
        if (resource.get("status") or "").lower() != "running":
            return None
        try:
            agent_resp = proxmox.nodes(node).qemu(vmid).agent(
                "network-get-interfaces"
            ).get() or {}
            return agent_resp.get("result") or []
        except Exception:
            # Guest agent not installed / not running — perfectly normal.
            return None

    @staticmethod
    def _proxmox_agent_hostname(proxmox, resource, node, vmid) -> Optional[str]:
        """Return the guest OS hostname via the agent, or None when unavailable.

        Only a running VM with qemu-guest-agent answers ``get-host-name``; any
        failure is swallowed (the Proxmox API exposes no hostname otherwise).
        """
        if (resource.get("status") or "").lower() != "running":
            return None
        try:
            agent_resp = proxmox.nodes(node).qemu(vmid).agent(
                "get-host-name"
            ).get() or {}
            result = agent_resp.get("result") or {}
            hostname = result.get("host-name")
            return hostname or None
        except Exception:
            return None

    def _proxmox_collect_vm(self, proxmox, resource, node, vmid) -> Optional[Dict[str, Any]]:
        """Discover a single Proxmox QEMU VM. Returns the VM dict or None."""
        try:
            config = proxmox.nodes(node).qemu(vmid).config.get() or {}
        except Exception as exc:
            logger.warning(f"Proxmox: config indisponible pour {node}/{vmid}: {exc}")
            config = {}

        agent_net = self._proxmox_agent_net(proxmox, resource, node, vmid)
        agent_hostname = self._proxmox_agent_hostname(proxmox, resource, node, vmid)

        try:
            vm_dict = _parse_proxmox_vm(resource, config, agent_net, agent_hostname)
        except Exception as exc:
            logger.error(f"Proxmox: parse échoué {node}/{vmid}: {exc}")
            return None

        logger.info(
            f"  Proxmox '{vm_dict['name']}' (vmid={vmid}@{node}): "
            f"cpus={vm_dict['cpu_cores']}, mem={vm_dict['memory_mb']}MB, "
            f"disk={vm_dict['disk_gb']}GB, power={vm_dict['power_state']}, "
            f"ip={vm_dict['ip_address']}"
        )
        return vm_dict

    def _discover_ovirt(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover VMs from oVirt / RHV.

        Uses ``ovirt-engine-sdk-python`` when it is importable (in-cluster Linux
        worker); otherwise falls back to the SDK-free REST client
        (:mod:`app.services.ovirt_rest`) — the SDK is a native C-extension that
        cannot be installed on the Windows dev worker, which is the only host
        able to reach the engine in the laptop topology.

        connection_config keys (all optional):
          ca_file   — PEM CA bundle for TLS verification
          api_path  — override '/ovirt-engine/api' (default)
        """
        from app.services.ovirt_rest import ovirt_sdk_available

        if not ovirt_sdk_available():
            return self._discover_ovirt_rest(hypervisor)

        import ovirtsdk4 as sdk

        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        host: str = hypervisor.host or "localhost"
        api_path: str = cfg.get("api_path") or "/ovirt-engine/api"
        port_str = f":{hypervisor.port}" if hypervisor.port else ""
        url = f"https://{host}{port_str}{api_path}"

        ca_file = cfg.get("ca_file") or hypervisor.ssl_cert_path or None
        insecure = not bool(hypervisor.verify_ssl)

        logger.info(
            f"oVirt: url={url}, user={hypervisor.username}, "
            f"insecure={insecure}, ca_file={ca_file}"
        )

        try:
            connection = sdk.Connection(
                url=url,
                username=hypervisor.username or "admin@internal",
                password=hypervisor.password_plain or "",
                ca_file=ca_file,
                insecure=insecure,
                timeout=30,
            )
        except Exception as exc:
            raise DiscoveryError(f"oVirt: échec de connexion à {url}: {exc}") from None

        try:
            system = connection.system_service()
            vms_service = system.vms_service()
            disks_service = system.disks_service()

            try:
                ovirt_vms = vms_service.list(all_content=True)
            except TypeError:
                # Older SDKs do not expose all_content
                ovirt_vms = vms_service.list()

            if not ovirt_vms:
                logger.info("oVirt: aucune VM trouvée — retour liste vide (déclenche ARCHIVE)")
                return []

            vms: List[Dict[str, Any]] = []
            for vm in ovirt_vms:
                vm_dict = self._ovirt_collect_vm(vms_service, disks_service, vm)
                if vm_dict is None:
                    continue
                vms.append(vm_dict)
                logger.info(
                    f"  oVirt '{vm_dict['name']}': cpus={vm_dict['cpu_cores']}, "
                    f"mem={vm_dict['memory_mb']}MB, disk={vm_dict['disk_gb']}GB, "
                    f"power={vm_dict['power_state']}, ip={vm_dict['ip_address']}"
                )
            return vms
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _collect_physical_facts(self, run) -> List[Dict[str, Any]]:
        """Run read-only fact commands via ``run`` and build the host VM dict.

        ``run(cmd) -> (stdout, stderr, rc)``. Split from :meth:`_discover_physical`
        so it can be unit-tested with a fake runner (no live SSH).
        """
        hostname = (run("hostname -f")[0] or run("hostname")[0] or "unknown").strip()

        os_release = run("cat /etc/os-release")[0]
        os_name, os_version = _parse_os_release(os_release)

        cpu_cores = _safe_int(run("nproc")[0], default=1)
        mem_total_kb = _grep_meminfo(run("grep MemTotal /proc/meminfo")[0])
        memory_mb = mem_total_kb // 1024

        uuid = run("cat /sys/class/dmi/id/product_uuid")[0].strip()
        # UEFI iff /sys/firmware/efi exists; otherwise the host booted legacy BIOS.
        firmware = _FW_EFI if "efi" in run(
            "[ -d /sys/firmware/efi ] && echo efi || echo bios"
        )[0] else _FW_BIOS
        boot_source = run("findmnt -n -o SOURCE /")[0].strip()
        lsblk_json = run("lsblk -b -J -o NAME,SIZE,TYPE,MOUNTPOINT")[0]
        disks = _parse_lsblk_disks(lsblk_json, boot_source) if lsblk_json.strip() else []

        ip_json = run("ip -j addr")[0]
        ip_address, mac_address = _parse_ip_json(ip_json)

        facts = {
            "hostname": hostname,
            "os_name": os_name,
            "os_version": os_version,
            "cpu_cores": cpu_cores,
            "memory_mb": memory_mb,
            "uuid": uuid,
            "firmware": firmware,
            "ip_address": ip_address,
            "mac_address": mac_address,
        }
        return [_build_physical_vm_dict(facts, disks)]

    def _discover_physical(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover a physical Linux server (P2V) over SSH.

        connection_config keys:
          ssh_key_path  — optional private key path (falls back to
                          settings.KVM_SSH_KEY_PATH, then agent/~/.ssh).
        Password auth via the credential vault (hypervisor.password_plain) is
        also supported. Returns exactly one VM dict representing the host.
        """
        import warnings as _warnings
        import paramiko
        from app.core.config import settings
        from app.core.ssh import apply_host_key_policy

        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        ssh_host = hypervisor.host or ""
        ssh_user = hypervisor.username or "root"
        ssh_key_path: Optional[str] = (
            cfg.get("ssh_key_path") or settings.KVM_SSH_KEY_PATH or None
        )
        password = hypervisor.password_plain or None

        logger.info(f"Physical P2V SSH: {ssh_user}@{ssh_host}")

        def _run(cmd: str):
            _, stdout, stderr = client.exec_command(cmd, timeout=20)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return out, err, rc

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            client = paramiko.SSHClient()
            apply_host_key_policy(client)  # Audit H-02
            try:
                client.connect(
                    ssh_host,
                    port=hypervisor.port or 22,
                    username=ssh_user,
                    password=password,
                    key_filename=ssh_key_path,
                    timeout=15,
                    look_for_keys=True,
                )
            except Exception as exc:
                client.close()  # Audit E8 — avoid transport/thread leak
                raise DiscoveryError(
                    f"SSH physical connection failed ({ssh_user}@{ssh_host}): {exc}"
                ) from None

        try:
            return self._collect_physical_facts(_run)
        finally:
            client.close()

    @staticmethod
    def _ovirt_disk_gb(vm_svc, disks_service, vm) -> int:
        """Sum the provisioned size of every disk attached to an oVirt VM."""
        disk_bytes = 0
        try:
            for att in vm_svc.disk_attachments_service().list() or []:
                if not att.disk or not att.disk.id:
                    continue
                try:
                    d = disks_service.disk_service(att.disk.id).get()
                    disk_bytes += int((d.provisioned_size or d.total_size or 0))
                except Exception:
                    continue
        except Exception as exc:
            logger.debug(
                "oVirt: disk attachments indisponibles pour "
                f"'{getattr(vm, 'name', '?')}': {exc}"
            )
        disk_gb = round(disk_bytes / 1_073_741_824) if disk_bytes else 0
        if disk_bytes and disk_gb == 0:
            disk_gb = 1
        return disk_gb

    def _ovirt_collect_vm(self, vms_service, disks_service, vm) -> Optional[Dict[str, Any]]:
        """Discover a single oVirt VM. Returns the VM dict or None on error."""
        try:
            vm_svc = vms_service.vm_service(vm.id)
            disk_gb = self._ovirt_disk_gb(vm_svc, disks_service, vm)

            # Reported devices — typically only populated on running VMs
            # with ovirt-guest-agent / qemu-guest-agent.
            try:
                devices: List[Any] = vm_svc.reported_devices_service().list() or []
            except Exception:
                devices = []

            return _parse_ovirt_vm(vm, disk_gb, devices)
        except Exception as exc:
            logger.error(
                f"oVirt: parse échoué pour '{getattr(vm, 'name', '?')}': {exc}"
            )
            return None

    # --- REST fallback (SDK-free) -------------------------------------------

    def _discover_ovirt_rest(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover oVirt VMs over the SDK-free REST client."""
        from app.services.ovirt_rest import OvirtRestClient, OvirtRestError

        try:
            client = OvirtRestClient(hypervisor)
        except OvirtRestError as exc:
            raise DiscoveryError(f"oVirt REST: {exc}") from None

        logger.info(
            f"oVirt (REST): {build_base_url(hypervisor)}, "
            f"user={hypervisor.username}, verify_ssl={hypervisor.verify_ssl}"
        )
        try:
            try:
                ovirt_vms = client.list_vms()
            except OvirtRestError as exc:
                raise DiscoveryError(
                    f"oVirt REST: échec de connexion à {hypervisor.host}: {exc}"
                ) from None

            if not ovirt_vms:
                logger.info("oVirt (REST): aucune VM trouvée — retour liste vide")
                return []

            vms: List[Dict[str, Any]] = []
            for vm in ovirt_vms:
                vm_dict = self._ovirt_collect_vm_rest(client, vm)
                if vm_dict is None:
                    continue
                vms.append(vm_dict)
                logger.info(
                    f"  oVirt '{vm_dict['name']}': cpus={vm_dict['cpu_cores']}, "
                    f"mem={vm_dict['memory_mb']}MB, disk={vm_dict['disk_gb']}GB, "
                    f"power={vm_dict['power_state']}, ip={vm_dict['ip_address']}"
                )
            return vms
        finally:
            client.close()

    def _ovirt_disk_gb_rest(self, client, vm_id: str) -> int:
        """Sum provisioned size across an oVirt VM's disks (REST)."""
        disk_bytes = 0
        try:
            for att in client.list_disk_attachments(vm_id):
                disk_id = (att.get("disk") or {}).get("id")
                if not disk_id:
                    continue
                try:
                    disk = client.get_disk(disk_id)
                except Exception:  # NOSONAR — skip a disk that cannot be read
                    continue
                disk_bytes += to_int(disk.get("provisioned_size")) or to_int(
                    disk.get("total_size")
                )
        except Exception as exc:  # NOSONAR
            logger.debug(f"oVirt (REST): disk attachments indisponibles pour {vm_id}: {exc}")
        disk_gb = round(disk_bytes / 1_073_741_824) if disk_bytes else 0
        if disk_bytes and disk_gb == 0:
            disk_gb = 1
        return disk_gb

    def _ovirt_collect_vm_rest(self, client, vm: dict) -> Optional[Dict[str, Any]]:
        """Discover a single oVirt VM via REST. Returns the VM dict or None."""
        from app.services.ovirt_rest import OvirtRestError

        try:
            vm_id = vm.get("id")
            disk_gb = self._ovirt_disk_gb_rest(client, vm_id)
            try:
                devices = client.list_reported_devices(vm_id)
            except OvirtRestError:
                devices = []
            return _parse_ovirt_vm_rest(vm, disk_gb, devices)
        except Exception as exc:  # NOSONAR
            logger.error(f"oVirt (REST): parse échoué pour '{vm.get('name', '?')}': {exc}")
            return None

    # ========================================================================
    # SAUVEGARDE ET SYNCHRONISATION DES VMs DÉCOUVERTES
    # ========================================================================

    def _reattach_by_uuid(
        self,
        hypervisor: Hypervisor,
        uuid: str,
    ) -> Optional[VirtualMachine]:
        """Pass-2 lookup: find a tenant VM by UUID and re-attach it.

        Extracted from ``_save_discovered_vms`` — Audit S3776. Locates a VM
        that was orphaned (hypervisor deleted with SET NULL) or imported from
        another hypervisor and re-attaches it to the current hypervisor so a
        duplicate row is not created. Returns the row, or ``None``.
        """
        existing_vm = (
            self.db.query(VirtualMachine)
            .filter(
                VirtualMachine.tenant_id == hypervisor.tenant_id,
                VirtualMachine.source_uuid == uuid,
            )
            .first()
        )
        if existing_vm:
            old_hyp_id = existing_vm.source_hypervisor_id
            existing_vm.source_hypervisor_id = hypervisor.id
            logger.info(
                f"🔗 VM ré-attachée à l'hyperviseur {hypervisor.id}: "
                f"{existing_vm.name} (anciennement hyp={old_hyp_id})"
            )
        return existing_vm

    def _sync_one_discovered_vm(
        self,
        hypervisor: Hypervisor,
        vm_data: Dict[str, Any],
        existing_vm: Optional[VirtualMachine],
        stats: Dict[str, int],
    ) -> None:
        """Apply one discovered VM to the DB (INSERT or UPDATE), updating stats.

        Extracted from ``_save_discovered_vms`` — Audit S3776. Behaviour is
        unchanged.
        """
        if existing_vm:
            changed = self._update_vm_from_discovery(existing_vm, vm_data)
            if changed:
                stats["updated_vms"] += 1
                logger.info(f"✏️  VM mise à jour: {vm_data['name']}")
            else:
                stats["unchanged_vms"] += 1
                logger.debug(f"✔  VM inchangée: {vm_data['name']}")
        else:
            new_vm = self._create_vm_from_discovery(hypervisor, vm_data)
            self.db.add(new_vm)
            self.db.flush()   # obtain new_vm.id before logging
            stats["new_vms"] += 1
            logger.info(f"➕ Nouvelle VM créée: {vm_data['name']} (ID: {new_vm.id})")

    def _save_discovered_vms(
        self,
        hypervisor: Hypervisor,
        vms_data: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        Synchronise les VMs découvertes avec la base de données.

        Sync rules (keyed on source_uuid):
        ┌─────────────────────────────────────────────┬───────────────────────┐
        │ Hypervisor          │ Database               │ Action                │
        ├─────────────────────┼────────────────────────┼───────────────────────┤
        │ VM present          │ Not found              │ INSERT (new discovery)│
        │ VM present          │ Found                  │ UPDATE if changed     │
        │ VM absent           │ Found (not protected)  │ Mark ARCHIVED         │
        └─────────────────────┴────────────────────────┴───────────────────────┘

        Also updates hypervisor.total_vms_discovered with the live count.

        Args:
            hypervisor: Hypervisor source.
            vms_data:   List of VM dicts returned by the discovery method.

        Returns:
            Statistics dict: total_discovered, new_vms, updated_vms,
                             archived_vms, unchanged_vms, errors.
        """
        stats = {
            "total_discovered": len(vms_data),
            "new_vms": 0,
            "updated_vms": 0,
            "unchanged_vms": 0,
            "archived_vms": 0,
            "errors": 0,
        }

        # Track every UUID actually returned by the hypervisor this run.
        discovered_uuids: set = set()

        for vm_data in vms_data:
            try:
                uuid = vm_data["source_uuid"]
                discovered_uuids.add(uuid)

                # ----------------------------------------------------------
                # Lookup: find existing DB record for this VM (3-pass).
                # ----------------------------------------------------------

                # Pass 1 — exact match: same hypervisor + same UUID.
                existing_vm: Optional[VirtualMachine] = (
                    self.db.query(VirtualMachine)
                    .filter(
                        VirtualMachine.source_hypervisor_id == hypervisor.id,
                        VirtualMachine.source_uuid == uuid,
                    )
                    .first()
                )

                # Pass 2 — UUID global fallback within the tenant: re-attach
                # an orphaned / cross-hypervisor VM to this hypervisor.
                if not existing_vm:
                    existing_vm = self._reattach_by_uuid(hypervisor, uuid)

                # Pass 3 — name fallback within this hypervisor.
                #
                # Audit E16 — restreint aux lignes dont source_uuid IS NULL.
                # Sans ce garde-fou, une VM dont l'UUID a simplement changé
                # (recréation, clone, changement de SMBIOS) verrait sa ligne
                # détournée par une VM homonyme — corruption d'identité. Une
                # ligne qui a déjà un source_uuid ne doit JAMAIS être
                # ré-appariée par le nom.
                if not existing_vm:
                    existing_vm = (
                        self.db.query(VirtualMachine)
                        .filter(
                            VirtualMachine.source_hypervisor_id == hypervisor.id,
                            VirtualMachine.name == vm_data["name"],
                            VirtualMachine.source_uuid.is_(None),
                        )
                        .first()
                    )

                # INSERT or UPDATE — extracted to a helper (Audit S3776).
                self._sync_one_discovered_vm(hypervisor, vm_data, existing_vm, stats)
            except (ValueError, KeyError, AttributeError, TypeError) as e:
                logger.error(
                    f"❌ Erreur sauvegarde VM {vm_data.get('name', 'unknown')}: {str(e)}"
                )
                logger.error(traceback.format_exc())
                stats["errors"] += 1

        # ------------------------------------------------------------------
        # ARCHIVE — VMs in DB that are no longer reported by the hypervisor.
        #
        # We always run the archive query, even when discovered_uuids is empty
        # (i.e. the hypervisor returned zero VMs this cycle), so that VMs
        # deleted from Workstation are properly archived.
        #
        # Protected statuses (MIGRATING, MIGRATED) are never touched.
        # ------------------------------------------------------------------
        _PROTECTED = {VMStatus.MIGRATING, VMStatus.MIGRATED}

        stale_query = (
            self.db.query(VirtualMachine)
            .filter(
                VirtualMachine.source_hypervisor_id == hypervisor.id,
                VirtualMachine.status != VMStatus.ARCHIVED,
                VirtualMachine.status.notin_(_PROTECTED),
            )
        )
        # Exclude UUIDs we just saw (only filter when the set is non-empty to
        # avoid an accidental "archive everything" when notin_([]) is a no-op).
        if discovered_uuids:
            stale_query = stale_query.filter(
                VirtualMachine.source_uuid.notin_(discovered_uuids)
            )

        for stale_vm in stale_query.all():
            stale_vm.status = VMStatus.ARCHIVED
            stats["archived_vms"] += 1
            logger.info(f"🗄️  VM archivée (disparue de l'hyperviseur): {stale_vm.name}")

        # ------------------------------------------------------------------
        # Sync hypervisor.total_vms_discovered with the live count.
        # We count every active (non-archived) VM attached to this hypervisor
        # after the sync so the number is always accurate.
        # ------------------------------------------------------------------
        # Commit first so the live count query sees all flushed changes
        self.db.commit()

        live_count: int = (
            self.db.query(VirtualMachine)
            .filter(
                VirtualMachine.source_hypervisor_id == hypervisor.id,
                VirtualMachine.status != VMStatus.ARCHIVED,
            )
            .count()
        )

        hypervisor.total_vms_discovered = live_count
        hypervisor.last_sync_at = datetime.now(timezone.utc)
        logger.info(f"🔢 total_vms_discovered mis à jour → {live_count}")
        self.db.commit()
        stats["live_count"] = live_count
        return stats

    def _create_vm_from_discovery(
        self,
        hypervisor: Hypervisor,
        vm_data: Dict[str, Any],
    ) -> VirtualMachine:
        """
        Crée une nouvelle entrée VirtualMachine depuis les données de découverte.

        Sets source_hypervisor_id, source_uuid, and all hardware/OS fields
        from vm_data.  status is set to DISCOVERED; compatibility_status
        comes from the discovery assessment (may be refined by the analyser
        pipeline later).
        """
        vm = VirtualMachine(
            name=vm_data["name"],
            tenant_id=hypervisor.tenant_id,
            source_hypervisor_id=hypervisor.id,        # ← FK to hypervisors.id
            source_uuid=vm_data["source_uuid"],         # ← stable identifier
            source_name=vm_data["source_name"],
            cpu_cores=vm_data.get("cpu_cores", 1),
            memory_mb=vm_data.get("memory_mb", 1024),
            disk_gb=vm_data.get("disk_gb", 0),
            os_type=vm_data.get("os_type"),
            os_version=vm_data.get("os_version"),
            os_name=vm_data.get("os_name"),
            ip_address=vm_data.get("ip_address"),
            mac_address=vm_data.get("mac_address"),
            hostname=vm_data.get("hostname"),
            status=VMStatus.DISCOVERED,
            compatibility_status=vm_data.get("compatibility_status", CompatibilityStatus.UNKNOWN),
            openshift_namespace=None,
            discovered_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            custom_metadata={
                k: vm_data[k]
                for k in ("power_state", "vmx_path", "tools_state", "firmware")
                if k in vm_data
            } or None,
        )
        # P2V: carry the per-disk capture plan so the converter connector
        # (PhysicalPuller.list_disks) can enumerate block devices later.
        if vm_data.get("physical_disks") is not None:
            existing = dict(vm.custom_metadata or {})
            existing["physical_disks"] = vm_data["physical_disks"]
            vm.custom_metadata = existing
        return vm

    def _update_vm_from_discovery(
        self,
        vm: VirtualMachine,
        vm_data: Dict[str, Any],
    ) -> bool:
        """
        Met à jour une VM existante avec les nouvelles données de découverte.

        Fields updated on every sync
        ----------------------------
        • source_hypervisor_id  — re-attached if the VM was orphaned
        • source_uuid           — back-fill if missing (legacy rows)
        • source_name           — display name may be renamed inside Workstation
        • Hardware specs        — cpu_cores, memory_mb, disk_gb are updated when
                                   the hypervisor reports a different value; VMs
                                   can be reconfigured without being re-created.
        • os_type / os_version / os_name — same rationale as hardware specs
        • ip_address / mac_address       — only when the new value is non-null
        • hostname                        — only when the new value is non-null
        • last_seen_at                    — always refreshed
        • custom_metadata (power_state, vmx_path, tools_state)

        Fields intentionally NOT touched
        ---------------------------------
        • status / compatibility_status  — managed by the analyser pipeline
        • discovered_at                  — immutable creation timestamp
        • openshift_* fields             — set by the migration pipeline

        Returns:
            True  — at least one field was changed (caller increments updated_vms)
            False — nothing changed (caller increments unchanged_vms)
        """
        changed = False

        # Reactivate VM if it was archived but is now seen again in the hypervisor
        if vm.status == VMStatus.ARCHIVED:
            vm.status = VMStatus.DISCOVERED
            changed = True
            logger.info(f"♻️  VM réactivée (réapparue dans l'hyperviseur): {vm.name}")

        def _set(attr: str, new_val: Any) -> None:
            nonlocal changed
            if new_val is not None and getattr(vm, attr) != new_val:
                setattr(vm, attr, new_val)
                changed = True

        # FK re-attach: source_hypervisor_id is set directly on the object by
        # _save_discovered_vms before calling this method — nothing to do here.

        # Back-fill source_uuid on legacy rows that predate UUID tracking
        if not vm.source_uuid and vm_data.get("source_uuid"):
            vm.source_uuid = vm_data["source_uuid"]
            changed = True

        # Hardware specs — update when the hypervisor reports something different
        _set("source_name", vm_data.get("source_name"))
        _set("cpu_cores",   vm_data.get("cpu_cores"))
        _set("memory_mb",   vm_data.get("memory_mb"))

        new_disk = vm_data.get("disk_gb")
        if new_disk is not None and new_disk > 0:
            _set("disk_gb", new_disk)

        # OS metadata
        _set("os_type",    vm_data.get("os_type"))
        _set("os_version", vm_data.get("os_version"))
        _set("os_name",    vm_data.get("os_name"))

        # Network — only overwrite when the new value is non-null so a
        # temporarily unreachable VM doesn't lose its last-known address.
        if vm_data.get("ip_address"):
            _set("ip_address", vm_data["ip_address"])
        if vm_data.get("mac_address"):
            _set("mac_address", vm_data["mac_address"])
        if vm_data.get("hostname"):
            _set("hostname", vm_data["hostname"])

        # Always refresh last_seen_at
        vm.last_seen_at = datetime.now(timezone.utc)
        changed = True   # last_seen_at is always considered a meaningful update

        # Merge live hypervisor metadata
        meta_keys = ("power_state", "vmx_path", "tools_state", "firmware")
        new_meta = {k: vm_data[k] for k in meta_keys if k in vm_data}
        # P2V: refresh the per-disk capture plan when present so the converter
        # connector (PhysicalPuller.list_disks) always sees the current layout.
        if vm_data.get("physical_disks") is not None:
            new_meta["physical_disks"] = vm_data["physical_disks"]
        if new_meta:
            current_meta = vm.custom_metadata or {}
            merged = {**current_meta, **new_meta}
            if merged != current_meta:
                vm.custom_metadata = merged
                changed = True

        return changed


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def create_discovery_service(db: Session) -> DiscoveryService:
    """Factory pour créer une instance du service de découverte."""
    return DiscoveryService(db)
