"""
Conversion planning — pick tool + target format for a given disk.

Decision matrix:
- source already QCOW2 + target QCOW2 + Linux/unknown guest -> PASSTHROUGH (skip convert, just checksum)
- Windows guest, any source -> VIRT_V2V (injects virtio drivers; required for KubeVirt boot)
- Linux/unknown guest, source != QCOW2 -> QEMU_IMG
- Otherwise -> QEMU_IMG (safe default)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.conversion import ConversionTool, SourceFormat, TargetFormat
from app.models.virtual_machine import OSType


@dataclass(frozen=True)
class ConversionPlan:
    tool: ConversionTool
    target_format: TargetFormat
    # Hint for virt-v2v guest type (only relevant when tool == VIRT_V2V).
    inject_virtio: bool


def plan_conversion(
    *,
    source_format: SourceFormat,
    target_format: TargetFormat,
    os_type: OSType,
) -> ConversionPlan:
    """Return the plan for one disk."""
    if os_type == OSType.WINDOWS:
        # Windows always needs virtio injection — virt-v2v handles both
        # the conversion and the driver inject in one pass.
        return ConversionPlan(
            tool=ConversionTool.VIRT_V2V,
            target_format=target_format,
            inject_virtio=True,
        )

    # Non-Windows
    same_format = source_format.value == target_format.value
    if same_format and source_format == SourceFormat.QCOW2:
        return ConversionPlan(
            tool=ConversionTool.PASSTHROUGH,
            target_format=target_format,
            inject_virtio=False,
        )

    return ConversionPlan(
        tool=ConversionTool.QEMU_IMG,
        target_format=target_format,
        inject_virtio=False,
    )
