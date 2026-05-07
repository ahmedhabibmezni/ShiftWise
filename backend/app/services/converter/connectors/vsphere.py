"""
vSphere stub connector.

Discovery already keeps vSphere as a stub (Broadcom ended free ESXi in
Feb 2024 — no test environment available). The converter follows the same
posture: fail loudly with a stable error code.
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


class VsphereStubPuller:
    """:class:`DiskPuller` placeholder for vSphere."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            "vSphere connector is a stub (no test environment available)",
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
            "vSphere connector is a stub (no test environment available)",
        )
