"""
oVirt / RHV connector — pull a disk via the ImageTransfer download API.

Strategy (cold pull, planned):
1. ``ovirt-engine-sdk-python``: open Connection, find vm by ``source_uuid``.
2. For each disk_attachment, get the disk; ensure status == OK.
3. Open an ``ImageTransfer`` with ``direction=download`` (creates a transfer URL).
4. Stream from the transfer URL via httpx (disabling SSL verify if hv.verify_ssl is False).
5. Finalize the transfer.

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


class OvirtPuller:
    """:class:`DiskPuller` for oVirt/RHV. Stub — see module docstring."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        raise ConversionError(
            "ERR_UNSUPPORTED_HYPERVISOR",
            "oVirt pull_disk not implemented yet",
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
            "oVirt pull_disk not implemented yet",
        )
