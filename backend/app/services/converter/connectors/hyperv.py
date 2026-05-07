"""
Hyper-V connector — pull a VHD/VHDX via PowerShell + SMB.

Strategy (cold pull, planned):
1. PowerShell ``Get-VM -Name <vm>`` -> ``Stop-VM -Force`` if running and cold mandated.
2. ``Export-VM -Name <vm> -Path <export-share>`` to a UNC path readable by the worker.
3. Copy the resulting .vhd/.vhdx into NFS, computing sha256.
4. Optional: ``Remove-Item`` on the export dir after success.

Not yet implemented — fail loudly via configurable bucket.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import (
    DiskDescriptor,
    DiskPuller,
    ProgressCallback,
    PullResult,
)


class HyperVPuller:
    """:class:`DiskPuller` for Hyper-V. Stub — see module docstring."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            "Hyper-V pull_disk not implemented yet",
        )

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
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            "Hyper-V pull_disk not implemented yet",
        )
