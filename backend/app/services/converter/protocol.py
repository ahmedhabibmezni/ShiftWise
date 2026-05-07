"""
Connector protocol — every hypervisor pull implementation must satisfy this
shape. Keeps the converter service decoupled from connector internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Callable

from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine


# Progress callback: (bytes_done, bytes_total) -> None.
# Connectors call it periodically during long pulls so the worker can
# update ConversionJob.progress_pct without blocking I/O.
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class DiskDescriptor:
    """Metadata about a single source disk on the hypervisor side."""
    disk_index: int
    source_format: SourceFormat
    size_bytes: int
    # Implementation-defined locator: VMX path, libvirt domain XML node,
    # Proxmox storage volume id, oVirt disk UUID, etc.
    locator: str


@dataclass(frozen=True)
class PullResult:
    """Result of a successful pull_disk() call."""
    staged_path: Path
    source_format: SourceFormat
    size_bytes: int
    sha256: Optional[str] = None  # filled if connector computes it inline


class DiskPuller(Protocol):
    """Per-hypervisor disk acquisition interface.

    All methods must raise ``ConversionError`` (not ``DiscoveryError``) on
    failure — the converter service catches only ``ConversionError`` to apply
    retry/bucket logic.
    """

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> list[DiskDescriptor]:
        """Enumerate the source disks of ``vm`` on ``hv``.

        Disk order is stable: index 0 is the boot disk by convention.
        """
        ...

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
        """Copy disk identified by ``descriptor`` from ``hv`` into ``dest_path``.

        ``cold`` = True means caller asserts the VM is powered off (or a snapshot
        is acceptable). False = best-effort live pull, per-connector support
        varies — connector raises ``ERR_VM_RUNNING_NEEDS_COLD`` if it cannot
        honour the live mode.

        Returns a ``PullResult`` pointing to the staged file. The caller is
        responsible for the eventual move into ``outputs/``.
        """
        ...
