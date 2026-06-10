r"""
Hyper-V connector — pull a VHD/VHDX, dual topology.

The Hyper-V host is Windows; the disk files live on its filesystem. Two worker
topologies are supported, selected by ``connection_config.auth_mode`` (mirrors
``discovery._discover_hyperv``):

* ``auth_mode == "local"``  — the ShiftWise worker runs **on the Hyper-V host**
  (Windows control plane). Disk enumeration uses local ``powershell.exe`` and the
  VHDX is a local file: ``pull_disk`` stream-copies it, ``convert_on_source`` runs
  the worker-local ``qemu-img`` directly.

* ``auth_mode == "winrm"`` (any non-local) — the worker runs elsewhere (Linux
  in-cluster). PowerShell is driven over **WinRM** (``pypsrp``) and the VHDX is
  pulled over **SMB** (``smbprotocol`` / ``smbclient``) from the host admin share
  (``\\host\C$\...``). For the SFTP bridge, ``convert_on_source`` pulls the VHDX
  to the worker scratch then converts locally.

A cold migration powers the VM off (``Stop-VM -Force``) before the read and
restarts it afterwards. There is no live Hyper-V test environment available — the
connector is written against documented PowerShell / WinRM / SMB behaviour and
covered by mocked unit tests for the pure helpers.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.connectors.base import (
    local_qemu_img_convert,
    sha256_file,
    stream_copy,
)
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)

logger = logging.getLogger(__name__)

_HASH_CHUNK = 1024 * 1024  # 1 MiB
_PS_TIMEOUT = 120  # seconds for metadata / control PowerShell calls


def _ps_lit(value: str) -> str:
    """Quote a value as a PowerShell single-quoted literal (escape ``'`` -> ``''``)."""
    return "'" + (value or "").replace("'", "''") + "'"


def _is_local(hv: Hypervisor) -> bool:
    cfg = hv.connection_config or {}
    return (cfg.get("auth_mode") or "local") == "local"


def _vhd_format(raw: str) -> SourceFormat:
    return SourceFormat.VHDX if (raw or "").lower() == "vhdx" else SourceFormat.VHD


def _to_unc(host: str, local_path: str) -> str:
    """Map a host-local Windows path (``C:\\d\\f.vhdx``) to its admin-share UNC."""
    if local_path.startswith("\\\\"):
        return local_path  # already a UNC path
    m = re.match(r"^([A-Za-z]):\\(.*)$", local_path)
    if not m:
        raise ConversionError(
            "ERR_DISK_NOT_FOUND",
            f"cannot map Hyper-V disk path to an SMB share: {local_path!r}",
        )
    drive, rest = m.group(1), m.group(2)
    return rf"\\{host}\{drive}$\{rest}"


def _build_list_script(uuid: str, name: str) -> str:
    """PowerShell that emits the VM's disks as JSON (path/size/filesize/format)."""
    return (
        "$ErrorActionPreference='Stop'\n"
        f"$uuid={_ps_lit(uuid)}\n"
        f"$name={_ps_lit(name)}\n"
        "$vm = Get-VM | Where-Object { ($_.Id.ToString() -replace '-','').ToLower() -eq $uuid }\n"
        "if (-not $vm) { $vm = Get-VM -Name $name }\n"
        "if (-not $vm) { throw 'VM not found' }\n"
        "$result = foreach ($d in $vm.HardDrives) {\n"
        "  $vhd = Get-VHD -Path $d.Path -ErrorAction SilentlyContinue\n"
        "  [PSCustomObject]@{\n"
        "    path     = $d.Path\n"
        "    size     = if ($vhd) { [int64]$vhd.Size } else { 0 }\n"
        "    filesize = if ($vhd) { [int64]$vhd.FileSize } else { 0 }\n"
        "    format   = if ($vhd) { \"$($vhd.VhdFormat)\" } else { '' }\n"
        "  }\n"
        "}\n"
        "$result | ConvertTo-Json -Depth 3\n"
    )


def _build_power_script(uuid: str, name: str, action: str) -> str:
    """PowerShell that stops/starts the VM. ``action`` is 'stop' or 'start'.

    Stop emits ``stopped`` only when it actually powered a running VM off, so the
    caller knows whether to restart it. Start is unconditional.
    """
    resolve = (
        f"$uuid={_ps_lit(uuid)}\n"
        f"$name={_ps_lit(name)}\n"
        "$vm = Get-VM | Where-Object { ($_.Id.ToString() -replace '-','').ToLower() -eq $uuid }\n"
        "if (-not $vm) { $vm = Get-VM -Name $name }\n"
        "if (-not $vm) { throw 'VM not found' }\n"
    )
    if action == "stop":
        return (
            "$ErrorActionPreference='Stop'\n" + resolve
            + "if ($vm.State -eq 'Running') { Stop-VM -VM $vm -Force -Confirm:$false; 'stopped' } "
            "else { 'already' }\n"
        )
    return "$ErrorActionPreference='Stop'\n" + resolve + "Start-VM -VM $vm -Confirm:$false\n"


def _run_ps_local(script: str, timeout: int = _PS_TIMEOUT) -> str:
    try:
        result = subprocess.run(  # NOSONAR — fixed argv, script not shell-interpolated
            ["powershell", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND",
            "powershell.exe not found; local Hyper-V access requires Windows",
            cause=e,
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ConversionError(
            "ERR_HV_UNREACHABLE", f"PowerShell timed out after {timeout}s", cause=e,
        ) from e
    if result.returncode != 0:
        raise ConversionError(
            "ERR_HV_UNREACHABLE",
            f"PowerShell failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout or 'no output').strip()}",
        )
    return result.stdout.strip()


def _run_ps_remote(hv: Hypervisor, script: str) -> str:
    try:
        from pypsrp.client import Client  # type: ignore
    except ImportError as e:
        raise ConversionError(
            "ERR_TOOL_NOT_FOUND",
            "pypsrp not installed in worker image (needed for remote Hyper-V)",
            cause=e,
        ) from e
    password = hv.password_plain
    if not hv.username or not password:
        raise ConversionError(
            "ERR_HV_CREDENTIALS_MISSING",
            f"remote Hyper-V access to {hv.host} requires username and password",
        )
    try:
        with Client(
            hv.host,
            username=hv.username,
            password=password,
            ssl=bool(hv.verify_ssl),
            cert_validation=bool(hv.verify_ssl),
        ) as client:
            stdout, _streams, had_errors = client.execute_ps(script)
    except Exception as e:  # NOSONAR — pypsrp raises various transport errors
        raise ConversionError(
            "ERR_HV_AUTH_FAILED",
            f"WinRM to Hyper-V host {hv.host} failed: {e}",
            cause=e,
        ) from e
    if had_errors:
        raise ConversionError(
            "ERR_HV_UNREACHABLE",
            f"remote PowerShell reported errors: {stdout.strip()[:500]}",
        )
    return stdout.strip()


def _run_ps(hv: Hypervisor, script: str, timeout: int = _PS_TIMEOUT) -> str:
    return _run_ps_local(script, timeout) if _is_local(hv) else _run_ps_remote(hv, script)


def _parse_disk_json(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConversionError(
            "ERR_INTERNAL", f"could not parse Hyper-V disk JSON: {e}", cause=e,
        ) from e
    return [data] if isinstance(data, dict) else list(data)


class HyperVPuller:
    """:class:`DiskPuller` for Hyper-V (local PowerShell or remote WinRM+SMB)."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        raw = _run_ps(hv, _build_list_script(vm.source_uuid or "", vm.name or ""))
        entries = _parse_disk_json(raw)
        descriptors: list[DiskDescriptor] = []
        for index, item in enumerate(entries):
            path = item.get("path")
            if not path:
                continue
            # Prefer the provisioned (virtual) size for free-space planning;
            # fall back to the on-disk file size for fixed/raw VHDs.
            size = int(item.get("size") or item.get("filesize") or 0)
            descriptors.append(
                DiskDescriptor(
                    disk_index=index,
                    source_format=_vhd_format(str(item.get("format") or "")),
                    size_bytes=size,
                    locator=str(path),
                )
            )
        if not descriptors:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"VM {vm.name!r}: no VHD/VHDX disks discovered on Hyper-V",
            )
        return descriptors

    def pull_disk(
        self,
        hv: Hypervisor,
        vm: VirtualMachine,
        descriptor: DiskDescriptor,
        dest_path: Path,
        *,
        cold: bool = True,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> PullResult:
        stopped_here = False
        if cold:
            stopped_here = self._stop_vm_if_running(hv, vm)
        try:
            if _is_local(hv):
                src = Path(descriptor.locator)
                if not src.is_file():
                    raise ConversionError(
                        "ERR_DISK_NOT_FOUND", f"VHD(X) not found on host: {src}",
                    )
                sha256 = stream_copy(
                    src, dest_path,
                    expected_size=descriptor.size_bytes,
                    progress_cb=progress_cb,
                )
            else:
                sha256 = self._smb_pull(
                    hv, descriptor.locator, dest_path,
                    descriptor.size_bytes, progress_cb,
                )
        finally:
            if stopped_here:
                self._start_vm_best_effort(hv, vm)
        return PullResult(
            staged_path=dest_path,
            source_format=descriptor.source_format,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    def convert_on_source(
        self,
        hv: Hypervisor,
        vm: VirtualMachine,
        descriptor: DiskDescriptor,
        dest_path: Path,
        *,
        target_format: str = "qcow2",
        cold: bool = True,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> PullResult:
        """Produce a compressed qcow2 in the worker scratch.

        Hyper-V hosts do not ship ``qemu-img``, so the VHDX is made available to
        the worker first (local file when ``auth_mode=local``, SMB pull otherwise)
        and converted with the worker-local ``qemu-img``.
        """
        stopped_here = False
        if cold:
            stopped_here = self._stop_vm_if_running(hv, vm)
        raw_tmp: Optional[Path] = None
        try:
            if _is_local(hv):
                src = Path(descriptor.locator)
                if not src.is_file():
                    raise ConversionError(
                        "ERR_DISK_NOT_FOUND", f"VHD(X) not found on host: {src}",
                    )
            else:
                raw_tmp = dest_path.with_suffix(dest_path.suffix + ".vhd")
                self._smb_pull(
                    hv, descriptor.locator, raw_tmp,
                    descriptor.size_bytes, progress_cb,
                )
                src = raw_tmp

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            partial = dest_path.with_suffix(dest_path.suffix + ".partial")
            try:
                local_qemu_img_convert(src, partial, target_format)
                partial.replace(dest_path)
            except ConversionError:
                partial.unlink(missing_ok=True)
                raise
        finally:
            if raw_tmp is not None:
                raw_tmp.unlink(missing_ok=True)
            if stopped_here:
                self._start_vm_best_effort(hv, vm)

        sha256 = sha256_file(dest_path)
        out_fmt = SourceFormat.QCOW2 if target_format == "qcow2" else SourceFormat.RAW
        return PullResult(
            staged_path=dest_path,
            source_format=out_fmt,
            size_bytes=dest_path.stat().st_size,
            sha256=sha256,
        )

    # --- internal helpers ---------------------------------------------------

    @staticmethod
    def _stop_vm_if_running(hv: Hypervisor, vm: VirtualMachine) -> bool:
        out = _run_ps(
            hv, _build_power_script(vm.source_uuid or "", vm.name or "", "stop"),
        )
        return out.strip().endswith("stopped")

    @staticmethod
    def _start_vm_best_effort(hv: Hypervisor, vm: VirtualMachine) -> None:
        try:
            _run_ps(
                hv, _build_power_script(vm.source_uuid or "", vm.name or "", "start"),
            )
        except ConversionError:  # NOSONAR — restart failure must not mask result
            logger.warning("could not restart Hyper-V VM %s after read", vm.name)

    @staticmethod
    def _smb_pull(
        hv: Hypervisor,
        remote_path: str,
        dest_path: Path,
        expected_size: int,
        progress_cb: Optional[ProgressCallback],
    ) -> str:
        try:
            import smbclient  # type: ignore
        except ImportError as e:
            raise ConversionError(
                "ERR_TOOL_NOT_FOUND",
                "smbprotocol not installed in worker image (needed for remote Hyper-V)",
                cause=e,
            ) from e
        import hashlib

        unc = _to_unc(hv.host, remote_path)
        password = hv.password_plain
        if not hv.username or not password:
            raise ConversionError(
                "ERR_HV_CREDENTIALS_MISSING",
                f"remote Hyper-V access to {hv.host} requires username and password",
            )
        smbclient.register_session(hv.host, username=hv.username, password=password)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        h = hashlib.sha256()
        bytes_done = 0
        try:
            with smbclient.open_file(unc, mode="rb") as fin, open(partial, "wb") as fout:
                while True:
                    buf = fin.read(_HASH_CHUNK)
                    if not buf:
                        break
                    fout.write(buf)
                    h.update(buf)
                    bytes_done += len(buf)
                    if progress_cb is not None:
                        try:
                            progress_cb(bytes_done, expected_size or bytes_done)
                        except Exception:  # NOSONAR
                            logger.debug("progress_cb raised", exc_info=True)
            partial.replace(dest_path)
        except Exception as e:  # NOSONAR
            partial.unlink(missing_ok=True)
            raise ConversionError(
                "ERR_NETWORK_TIMEOUT",
                f"SMB pull from {unc} failed: {e}",
                cause=e,
            ) from e
        return h.hexdigest()


# Structural conformance check (Protocol) — kept explicit for readers.
_: DiskPuller = HyperVPuller()
