"""
Error catalog for the converter pipeline.

Three buckets drive retry policy:
- TRANSIENT    : auto-retry with exponential backoff
- CONFIGURABLE : operator-fixable, manual retry only
- PERMANENT    : never retry, mark FAILED, surface to UI

Every ConversionError carries a stable ``code`` that is persisted on
``ConversionJob.error_code`` and used by the UI / metrics.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class ErrorBucket(str, enum.Enum):
    TRANSIENT = "transient"
    CONFIGURABLE = "configurable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    bucket: ErrorBucket
    description: str


# Stable catalog — codes persisted in DB; do not rename without a migration plan.
ERROR_CATALOG: dict[str, ErrorSpec] = {
    spec.code: spec
    for spec in (
        # Transient — auto-retry
        ErrorSpec("ERR_NFS_TIMEOUT", ErrorBucket.TRANSIENT, "NFS I/O timeout"),
        ErrorSpec("ERR_NFS_STALE_HANDLE", ErrorBucket.TRANSIENT, "NFS stale file handle"),
        ErrorSpec("ERR_TOOL_KILLED_OOM", ErrorBucket.TRANSIENT, "Tool killed by OOM"),
        ErrorSpec("ERR_HV_TRANSIENT", ErrorBucket.TRANSIENT, "Hypervisor temporary failure"),
        ErrorSpec("ERR_NETWORK_TIMEOUT", ErrorBucket.TRANSIENT, "Network timeout"),

        # Configurable — operator action required
        ErrorSpec("ERR_NFS_INSUFFICIENT_SPACE", ErrorBucket.CONFIGURABLE, "Not enough free space on NFS"),
        ErrorSpec("ERR_TOOL_NOT_FOUND", ErrorBucket.CONFIGURABLE, "Conversion tool not installed"),
        ErrorSpec("ERR_HV_AUTH_FAILED", ErrorBucket.CONFIGURABLE, "Hypervisor authentication failed"),
        ErrorSpec("ERR_HV_UNREACHABLE", ErrorBucket.CONFIGURABLE, "Hypervisor unreachable"),
        ErrorSpec("ERR_K8S_JOB_DENIED", ErrorBucket.CONFIGURABLE, "Kubernetes refused the conversion Job"),
        ErrorSpec("ERR_VM_RUNNING_NEEDS_COLD", ErrorBucket.CONFIGURABLE, "VM is running but cold pull requested"),

        # Permanent — never retry
        ErrorSpec("ERR_SOURCE_CORRUPT", ErrorBucket.PERMANENT, "Source disk is corrupt or unreadable"),
        ErrorSpec("ERR_UNSUPPORTED_FORMAT", ErrorBucket.PERMANENT, "Source format not supported"),
        ErrorSpec("ERR_VIRT_V2V_INSPECTION_FAILED", ErrorBucket.PERMANENT, "virt-v2v guest inspection failed"),
        ErrorSpec("ERR_CHECKSUM_MISMATCH", ErrorBucket.PERMANENT, "Output checksum verification failed"),
        ErrorSpec("ERR_OUTPUT_INVALID", ErrorBucket.PERMANENT, "Output disk failed qemu-img check"),
        ErrorSpec("ERR_VM_NOT_FOUND", ErrorBucket.PERMANENT, "VM no longer exists on the source hypervisor"),
        ErrorSpec("ERR_DISK_NOT_FOUND", ErrorBucket.PERMANENT, "Disk index does not exist on source VM"),
        ErrorSpec("ERR_UNSUPPORTED_HYPERVISOR", ErrorBucket.PERMANENT, "Hypervisor type not supported"),
        ErrorSpec("ERR_INTERNAL", ErrorBucket.PERMANENT, "Internal converter error"),
    )
}


class ConversionError(Exception):
    """Raised by connectors / converter pipeline.

    The ``code`` MUST be a key from ``ERROR_CATALOG``. Unknown codes default
    to ``ERR_INTERNAL`` (permanent) — fail loudly rather than silently retry.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        spec = ERROR_CATALOG.get(code)
        if spec is None:
            spec = ERROR_CATALOG["ERR_INTERNAL"]
            message = f"[unknown code {code!r}] {message}"
        self.code = spec.code
        self.bucket = spec.bucket
        self.message = message
        self.__cause__ = cause
        super().__init__(f"{self.code}: {message}")

    @property
    def is_retryable(self) -> bool:
        return self.bucket == ErrorBucket.TRANSIENT


def is_transient(code: str) -> bool:
    spec = ERROR_CATALOG.get(code)
    return spec is not None and spec.bucket == ErrorBucket.TRANSIENT
