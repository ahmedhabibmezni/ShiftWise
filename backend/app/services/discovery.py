"""
Discovery Service - Découverte des VMs depuis les hyperviseurs sources

Supporte :
- VMware vSphere (via pyvmomi)
- VMware Workstation (via vmrun)
- Hyper-V (via PowerShell)
- KVM/QEMU (via libvirt)
"""

import json
import os
import re
import subprocess
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging

from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus, OSType

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
        raise DiscoveryError(f"vmrun timeout ({timeout}s): {' '.join(cmd)}")
    except FileNotFoundError:
        raise DiscoveryError(f"vmrun introuvable à: {vmrun_path}")

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
        raise DiscoveryError(f"Impossible de lire {vmx_path}: {exc}")

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


def _vmx_disk_gb(vmx_path: str) -> int:
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
    disk_gb = _vmx_disk_gb(vmx_path)
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
                rv_hostname = _vmrun_read_variable(vmrun_path, vmx_path, "hostname")
                rv_os       = _vmrun_read_variable(vmrun_path, vmx_path, "os")
                rv_kernel   = _vmrun_read_variable(vmrun_path, vmx_path, "kernelVersion")

                if rv_hostname:
                    hostname_val = rv_hostname
                if rv_os:
                    os_name = rv_os
                if rv_kernel:
                    os_version = rv_kernel

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

            if os_type in (OSType.LINUX, OSType.WINDOWS):
                compatibility_status = CompatibilityStatus.COMPATIBLE
    else:
        tools_state = _get_tools_state(vmrun_path, vmx_path)
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
        "hostname": hostname_val,
        "power_state": power_state,
        "vmx_path": vmx_path,
        "tools_state": tools_state,
        "compatibility_status": compatibility_status,
    }


# ============================================================================
# Hyper-V helpers
# ============================================================================

# PowerShell script executed on the Hyper-V host to enumerate all VMs as JSON.
# Uses Get-VM (all power states) + Get-VHD for disk size.
_HYPERV_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
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

    [PSCustomObject]@{
        name         = $vm.Name
        source_uuid  = ($vm.Id.ToString() -replace '-', '').ToLower()
        cpu_cores    = [int]$vm.ProcessorCount
        memory_mb    = [int]($vm.MemoryAssigned / 1MB)
        disk_gb      = [int][Math]::Round($diskBytes / 1GB, 0)
        power_state  = $state
        ip_address   = $ip
        mac_address  = $mac
        hostname     = $vm.ComputerName
    }
}
$result | ConvertTo-Json -Depth 3
"""

# Remote wrapper: reads all sensitive values from env vars so that no credential
# ever appears in a command-line argument (prevents shell/PS injection).
_HYPERV_REMOTE_PS_WRAPPER = r"""
$pass = ConvertTo-SecureString $env:HV_PASS -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential($env:HV_USER, $pass)
$sb   = [scriptblock]::Create($env:HV_SCRIPT)
Invoke-Command -ComputerName $env:HV_HOST -Credential $cred -ScriptBlock $sb
"""


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
    extra_env = {
        "HV_PASS":   password,
        "HV_USER":   username,
        "HV_HOST":   host,
        "HV_SCRIPT": _HYPERV_PS_SCRIPT,
    }
    return ["powershell", "-NonInteractive", "-Command", _HYPERV_REMOTE_PS_WRAPPER], extra_env


def _parse_hyperv_output(stdout: str) -> List[Dict[str, Any]]:
    """Parse la sortie JSON de PowerShell en liste de dicts VM standardisés."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"Impossible de parser la sortie JSON PowerShell: {exc}")

    # PowerShell emits a bare object (not array) when exactly one VM exists
    if isinstance(data, dict):
        data = [data]

    vms: List[Dict[str, Any]] = []
    for item in data:
        vms.append({
            "source_uuid":          item.get("source_uuid") or "",
            "source_name":          item.get("name") or "unknown",
            "name":                 item.get("name") or "unknown",
            "cpu_cores":            int(item.get("cpu_cores") or 0),
            "memory_mb":            int(item.get("memory_mb") or 0),
            "disk_gb":              int(item.get("disk_gb") or 0),
            "os_type":              OSType.UNKNOWN,
            "os_version":           "N/A",
            "os_name":              "N/A",
            "ip_address":           item.get("ip_address"),
            "mac_address":          item.get("mac_address"),
            "hostname":             item.get("hostname"),
            "power_state":          item.get("power_state") or "unknown",
            "compatibility_status": CompatibilityStatus.UNKNOWN,
        })
    return vms


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
    import xml.etree.ElementTree as ET
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

    return {
        "source_uuid":          uuid,
        "source_name":          name,
        "name":                 name,
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


class DiscoveryService:
    """Service de découverte des VMs depuis les hyperviseurs"""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # MÉTHODES PRINCIPALES
    # ========================================================================

    def discover_hypervisor(self, hypervisor_id: int) -> Dict[str, Any]:
        """
        Découvre toutes les VMs d'un hypervisor

        Args:
            hypervisor_id: ID de l'hypervisor à scanner

        Returns:
            Statistiques de découverte

        Raises:
            DiscoveryError: Si la découverte échoue
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
            if hypervisor.type == HypervisorType.VSPHERE:
                vms_data = self._discover_vsphere(hypervisor)
            elif hypervisor.type == HypervisorType.VMWARE_WORKSTATION:
                vms_data = self._discover_vmware_workstation(hypervisor)
            elif hypervisor.type == HypervisorType.HYPER_V:
                vms_data = self._discover_hyperv(hypervisor)
            elif hypervisor.type == HypervisorType.KVM:
                vms_data = self._discover_kvm(hypervisor)
            else:
                raise DiscoveryError(f"Type d'hypervisor non supporté: {hypervisor.type}")

            stats = self._save_discovered_vms(hypervisor, vms_data)

            hypervisor.update_status(HypervisorStatus.ACTIVE)
            hypervisor.mark_sync_completed(success=True, total_vms=stats['total_discovered'])
            self.db.commit()

            logger.info(f"Découverte terminée: {stats['total_discovered']} VMs trouvées")
            return stats

        except (DiscoveryError, ConnectionError, TimeoutError) as e:
            logger.error(f"Erreur découverte hypervisor {hypervisor.name}: {str(e)}")
            hypervisor.update_status(HypervisorStatus.ERROR, error_message=str(e))
            hypervisor.mark_sync_completed(success=False)
            self.db.commit()
            raise DiscoveryError(f"Échec de la découverte: {str(e)}")

    # ========================================================================
    # DÉCOUVERTE PAR TYPE D'HYPERVISOR
    # ========================================================================

    def _discover_vsphere(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Découvre les VMs depuis vSphere (stub — pyvmomi non encore implémenté)."""
        logger.info(f"Connexion à vSphere: {hypervisor.host}")
        try:
            logger.warning("⚠️  Mode SIMULATION - pyvmomi non encore implémenté")
            return [
                {
                    "source_uuid": "vm-001-vsphere",
                    "source_name": "web-server-prod",
                    "name": "web-server-prod",
                    "cpu_cores": 4,
                    "memory_mb": 8192,
                    "disk_gb": 100,
                    "os_type": OSType.LINUX,
                    "os_version": "Ubuntu 22.04",
                    "os_name": "Ubuntu Server 22.04 LTS",
                    "ip_address": "192.168.1.10",
                    "mac_address": "00:50:56:00:00:01",
                    "hostname": "web-prod-01",
                    "power_state": "poweredOn",
                },
                {
                    "source_uuid": "vm-002-vsphere",
                    "source_name": "db-server-prod",
                    "name": "db-server-prod",
                    "cpu_cores": 8,
                    "memory_mb": 16384,
                    "disk_gb": 500,
                    "os_type": OSType.LINUX,
                    "os_version": "CentOS 8",
                    "os_name": "CentOS 8 Stream",
                    "ip_address": "192.168.1.11",
                    "mac_address": "00:50:56:00:00:02",
                    "hostname": "db-prod-01",
                    "power_state": "poweredOn",
                },
                {
                    "source_uuid": "vm-003-vsphere",
                    "source_name": "win-app-server",
                    "name": "win-app-server",
                    "cpu_cores": 2,
                    "memory_mb": 4096,
                    "disk_gb": 80,
                    "os_type": OSType.WINDOWS,
                    "os_version": "Windows Server 2019",
                    "os_name": "Windows Server 2019 Standard",
                    "ip_address": "192.168.1.12",
                    "mac_address": "00:50:56:00:00:03",
                    "hostname": "win-app-01",
                    "power_state": "poweredOn",
                },
            ]
        except Exception as e:
            raise DiscoveryError(f"Erreur connexion vSphere: {str(e)}")

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
             c. Directory scan of ``connection_config["vm_folder"]`` (covers all
                powered-off VMs without explicit registration).
        4. Parse each .vmx file and query live data (IP, tools state).
        5. Return the list — _save_discovered_vms handles all DB sync.
        """
        logger.info("Découverte VMware Workstation (vmrun réel)")

        # 1. Locate vmrun
        if hypervisor.host and os.path.isfile(hypervisor.host):
            vmrun_path = hypervisor.host
            logger.info(f"vmrun depuis hypervisor.host: {vmrun_path}")
        else:
            vmrun_path = _find_vmrun()
            logger.info(f"vmrun auto-détecté: {vmrun_path}")

        # 2. Get currently running VMX paths
        running_paths = _get_running_vmx_paths(vmrun_path)
        logger.info(f"VMs en cours d'exécution: {len(running_paths)}")
        for p in running_paths:
            logger.info(f"  - {p}")

        # 3. Build complete set of VMX paths to inspect
        vmx_paths_to_scan: List[str] = list(running_paths)

        # Extra VMX paths from connection_config["extra_vmx_paths"]
        extra_vmx: List[str] = []
        try:
            import json
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
        except Exception:
            pass

        for vmx in extra_vmx:
            norm = vmx.replace("\\", "/").lower()
            already = any(p.replace("\\", "/").lower() == norm for p in vmx_paths_to_scan)
            if not already:
                vmx_paths_to_scan.append(vmx)

        # Directory scan: walk vm_folder to discover ALL .vmx files
        cfg = hypervisor.connection_config or {}
        vm_folder: Optional[str] = None
        if isinstance(cfg, dict):
            vm_folder = cfg.get("vm_folder")

        if not vm_folder:
            _DEFAULT_VM_FOLDERS = [
                os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "Virtual Machines"),
                os.path.join(os.path.expanduser("~"), "Documents", "Virtual Machines"),
                os.path.join(os.path.expanduser("~"), "Virtual Machines"),
                "/var/lib/vmware/Virtual Machines",
            ]
            for candidate in _DEFAULT_VM_FOLDERS:
                if os.path.isdir(candidate):
                    vm_folder = candidate
                    logger.info(f"vm_folder auto-détecté: {vm_folder}")
                    break

        if vm_folder and os.path.isdir(vm_folder):
            logger.info(f"Scan du dossier VM: {vm_folder}")
            for root, _dirs, files in os.walk(vm_folder):
                for fname in files:
                    if fname.lower().endswith(".vmx"):
                        full_path = os.path.join(root, fname)
                        norm = full_path.replace("\\", "/").lower()
                        already = any(p.replace("\\", "/").lower() == norm for p in vmx_paths_to_scan)
                        if not already:
                            vmx_paths_to_scan.append(full_path)
                            logger.info(f"  VMX trouvé par scan dossier: {full_path}")
        else:
            if not vmx_paths_to_scan:
                logger.warning(
                    "Aucun VMX trouvé. Configurez 'vm_folder' dans connection_config "
                    'ex: {"vm_folder": "C:\\\\Users\\\\PC\\\\Documents\\\\Virtual Machines"}'
                )

        # 4. Extract optional guest credentials for runScriptInGuest
        guest_creds: Optional[Dict[str, str]] = None
        cfg = hypervisor.connection_config or {}
        if isinstance(cfg, dict) and cfg.get("guest_username"):
            guest_creds = {
                "username": cfg["guest_username"],
                "password": cfg.get("guest_password", ""),
            }

        # 5. Parse each VMX and gather live data
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
            host, auth_mode, hypervisor.username, hypervisor.password
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
            )
        except subprocess.TimeoutExpired:
            raise DiscoveryError(
                f"PowerShell timeout (120s) lors de la découverte Hyper-V id={hypervisor.id}"
            )

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

    def _discover_kvm(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """Discover KVM/QEMU VMs via SSH + virsh using paramiko.

        connection_config keys:
          auth_mode     — "ssh_key" (default) | "local" (qemu:///system, no SSH)
          ssh_key_path  — path to private key (default: C:/Users/PC/.ssh/id_rsa_kvm)
        """
        import warnings as _warnings
        import xml.etree.ElementTree as ET
        import paramiko

        cfg: Dict[str, Any] = hypervisor.connection_config or {}
        host_uri: str = hypervisor.host or "qemu:///system"

        ssh_match = re.match(r"qemu\+ssh://(?:([^@]+)@)?([^/?]+)", host_uri)
        if not ssh_match:
            raise DiscoveryError(
                f"KVM URI non supportée (attendu qemu+ssh://user@host/system): {host_uri}"
            )

        ssh_user: str = ssh_match.group(1) or "root"
        ssh_host: str = ssh_match.group(2)
        ssh_key_path: str = cfg.get("ssh_key_path") or "C:/Users/PC/.ssh/id_rsa_kvm"

        logger.info(f"KVM SSH: {ssh_user}@{ssh_host}, key={ssh_key_path}")

        def _run(client: paramiko.SSHClient, cmd: str):
            _, stdout, stderr = client.exec_command(cmd)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return out, err, rc

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    ssh_host,
                    username=ssh_user,
                    key_filename=ssh_key_path,
                    timeout=15,
                    look_for_keys=True,
                )
            except Exception as exc:
                raise DiscoveryError(f"SSH KVM connection failed ({ssh_user}@{ssh_host}): {exc}")

        VIRSH = "virsh --connect qemu:///system"

        try:
            names_out, names_err, names_rc = _run(client, f"{VIRSH} list --all --name")
            if names_rc != 0:
                raise DiscoveryError(f"virsh list failed: {names_err}")

            domain_names = [n for n in names_out.splitlines() if n.strip()]
            if not domain_names:
                logger.info("KVM: no domains found")
                return []

            vms: List[Dict[str, Any]] = []

            for name in domain_names:
                try:
                    xml_out, xml_err, xml_rc = _run(client, f"{VIRSH} dumpxml '{name}'")
                    if xml_rc != 0:
                        logger.error(f"KVM dumpxml failed for '{name}': {xml_err}")
                        continue

                    state_out, _, _ = _run(client, f"{VIRSH} domstate '{name}'")
                    state_str = state_out.strip()

                    root_el = ET.fromstring(xml_out)
                    disk_paths = []
                    for disk_el in root_el.findall(".//disk[@device='disk']"):
                        src = disk_el.find("source")
                        if src is not None:
                            path = src.get("file") or src.get("dev") or ""
                            if path:
                                disk_paths.append(path)

                    disk_sizes: Dict[str, int] = {}
                    for path in disk_paths:
                        img_out, _, img_rc = _run(
                            client,
                            f"qemu-img info --output=json '{path}' 2>/dev/null",
                        )
                        if img_rc == 0 and img_out:
                            try:
                                vsize = json.loads(img_out).get("virtual-size", 0)
                                disk_sizes[path] = max(1, round(vsize / 1_073_741_824))
                            except (ValueError, KeyError):
                                disk_sizes[path] = 0

                    vm_dict = _parse_kvm_domain_xml(xml_out, state_str, disk_sizes)
                    vms.append(vm_dict)
                    logger.info(
                        f"  KVM '{vm_dict['name']}': cpus={vm_dict['cpu_cores']}, "
                        f"mem={vm_dict['memory_mb']}MB, power={vm_dict['power_state']}, "
                        f"disk={vm_dict['disk_gb']}GB, uuid={vm_dict['source_uuid']}"
                    )
                except ET.ParseError as exc:
                    logger.error(f"KVM XML parse error for '{name}': {exc}")
                except Exception as exc:
                    logger.error(f"KVM error processing domain '{name}': {exc}")

            return vms
        finally:
            client.close()

    # ========================================================================
    # SAUVEGARDE DES VMs DÉCOUVERTES
    # ========================================================================

    def _save_discovered_vms(
            self,
            hypervisor: Hypervisor,
            vms_data: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Sauvegarde les VMs découvertes dans la base de données

        Args:
            hypervisor: Hypervisor source
            vms_data: Liste des VMs découvertes

        Returns:
            Statistiques (total, nouvelles, mises à jour)
        """
        stats = {
            "total_discovered": len(vms_data),
            "new_vms": 0,
            "updated_vms": 0,
            "errors": 0
        }

        for vm_data in vms_data:
            try:
                existing_vm = self.db.query(VirtualMachine).filter(
                    VirtualMachine.source_hypervisor_id == hypervisor.id,
                    VirtualMachine.source_uuid == vm_data["source_uuid"]
                ).first()

                if not existing_vm:
                    existing_vm = self.db.query(VirtualMachine).filter(
                        VirtualMachine.source_hypervisor_id == hypervisor.id,
                        VirtualMachine.name == vm_data["name"]
                    ).first()

                if existing_vm:
                    self._update_vm_from_discovery(existing_vm, vm_data)
                    stats["updated_vms"] += 1
                    logger.info(f"✅ VM mise à jour: {vm_data['name']}")
                else:
                    new_vm = self._create_vm_from_discovery(hypervisor, vm_data)
                    self.db.add(new_vm)
                    self.db.flush()
                    stats["new_vms"] += 1
                    logger.info(f"✅ Nouvelle VM créée: {vm_data['name']} (ID: {new_vm.id})")

            except (ValueError, KeyError, AttributeError, TypeError) as e:
                logger.error(f"❌ Erreur sauvegarde VM {vm_data.get('name', 'unknown')}: {str(e)}")
                logger.error(traceback.format_exc())
                stats["errors"] += 1

        self.db.commit()

        return stats

    def _create_vm_from_discovery(
            self,
            hypervisor: Hypervisor,
            vm_data: Dict[str, Any]
    ) -> VirtualMachine:
        """
        Crée une nouvelle VM depuis les données de découverte

        Args:
            hypervisor: Hypervisor source
            vm_data: Données de la VM découverte

        Returns:
            Instance VirtualMachine
        """
        vm = VirtualMachine(
            name=vm_data["name"],
            tenant_id=hypervisor.tenant_id,
            source_hypervisor_id=hypervisor.id,
            source_uuid=vm_data["source_uuid"],
            source_name=vm_data["source_name"],
            cpu_cores=vm_data.get("cpu_cores", 1),
            memory_mb=vm_data.get("memory_mb", 1024),
            disk_gb=vm_data.get("disk_gb", 10),
            os_type=vm_data.get("os_type"),
            os_version=vm_data.get("os_version"),
            os_name=vm_data.get("os_name"),
            ip_address=vm_data.get("ip_address"),
            mac_address=vm_data.get("mac_address"),
            hostname=vm_data.get("hostname"),
            status=VMStatus.DISCOVERED,
            compatibility_status=CompatibilityStatus.UNKNOWN,
            discovered_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc)
        )

        return vm

    def _update_vm_from_discovery(
            self,
            vm: VirtualMachine,
            vm_data: Dict[str, Any]
    ) -> None:
        """
        Met à jour une VM existante avec les nouvelles données

        Args:
            vm: VM existante à mettre à jour
            vm_data: Nouvelles données de découverte
        """
        vm.cpu_cores = vm_data.get("cpu_cores", vm.cpu_cores)
        vm.memory_mb = vm_data.get("memory_mb", vm.memory_mb)
        vm.disk_gb = vm_data.get("disk_gb", vm.disk_gb)
        vm.ip_address = vm_data.get("ip_address", vm.ip_address)
        vm.mac_address = vm_data.get("mac_address", vm.mac_address)
        vm.hostname = vm_data.get("hostname", vm.hostname)
        vm.os_version = vm_data.get("os_version", vm.os_version)
        vm.last_seen_at = datetime.now(timezone.utc)

        if vm.status not in [VMStatus.MIGRATING, VMStatus.MIGRATED]:
            vm.status = VMStatus.DISCOVERED


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def create_discovery_service(db: Session) -> DiscoveryService:
    """Factory pour créer une instance du service de découverte"""
    return DiscoveryService(db)
