"""
Physical server (P2V) connector — capture each block device of a bare-metal
Linux host as a raw stream over SSH.

Strategy (POSIX-minimal source — dd/gzip/ssh only):
  list_disks       : read the per-disk plan captured at discovery time.
  pull_disk        : ``dd if=<dev> bs=4M | gzip -1`` on the source, stream the
                     gzip over the SSH channel, gunzip into a staged .raw on
                     NFS. (implemented in a later task)
  convert_on_source: dev SFTP-bridge path. (implemented in a later task)
"""

from __future__ import annotations

import logging
import shlex
from typing import List

from app.models.conversion import SourceFormat
from app.models.hypervisor import Hypervisor
from app.models.virtual_machine import VirtualMachine
from app.services.converter.errors import ConversionError
from app.services.converter.protocol import DiskDescriptor

logger = logging.getLogger(__name__)

_PLAN_KEY = "physical_disks"


def build_capture_command(device: str) -> str:
    """Return the remote shell command that streams a gzipped raw disk.

    ``conv=noerror,sync`` keeps the stream length stable on a read error; the
    free-space regions compress away, so only used blocks cross the wire.
    """
    safe_dev = shlex.quote(device)
    return f"dd if={safe_dev} bs=4M conv=noerror,sync 2>/dev/null | gzip -1"


def _disk_plan(vm: VirtualMachine) -> list[dict]:
    meta = getattr(vm, "custom_metadata", None) or {}
    return list(meta.get(_PLAN_KEY) or [])


class PhysicalPuller:
    """:class:`DiskPuller` for bare-metal Linux servers (P2V)."""

    def list_disks(self, hv: Hypervisor, vm: VirtualMachine) -> List[DiskDescriptor]:
        plan = _disk_plan(vm)
        if not plan:
            raise ConversionError(
                "ERR_DISK_NOT_FOUND",
                f"physical host {getattr(vm, 'name', '?')}: no block-device plan "
                "captured at discovery — re-run discovery on the source",
            )
        descriptors: list[DiskDescriptor] = []
        for index, disk in enumerate(plan):
            descriptors.append(
                DiskDescriptor(
                    disk_index=index,
                    source_format=SourceFormat.RAW,
                    size_bytes=int(disk.get("size_bytes") or 0),
                    locator=disk.get("device") or "",
                )
            )
        return descriptors

    # pull_disk / convert_on_source implemented in later tasks.
