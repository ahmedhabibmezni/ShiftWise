"""
VMware Workstation connector — pull a VMDK from the workstation host.

Strategy (cold pull, planned):
1. Locate the VMX via existing ``services.discovery._find_vmrun`` / VMX scan.
2. Confirm the VM is powered off via ``vmrun list``.
3. Parse VMX for disk descriptors (``scsi0:0.fileName``, ``ide0:0.fileName``).
4. Each disk file is sibling-relative to the VMX. Copy via local filesystem
   if the worker shares the disk; else remote SCP/SMB.
5. Always pull the descriptor + extents (VMDK can be split or sparse).

Not yet implemented — fail loudly so the orchestrator routes the error
through the configurable bucket.
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


class VmwareWorkstationPuller:
    """:class:`DiskPuller` for VMware Workstation. Stub — see module docstring."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            "VMware Workstation pull_disk not implemented yet",
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
            "VMware Workstation pull_disk not implemented yet",
        )
