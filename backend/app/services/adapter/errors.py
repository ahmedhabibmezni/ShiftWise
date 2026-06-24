"""
Error catalog for the Adapter stage.

Same three-bucket model as the converter and migrator. Codes are
persisted on Migration.error_code, never rename without a migration plan.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class AdapterErrorBucket(str, enum.Enum):
    TRANSIENT = "transient"
    CONFIGURABLE = "configurable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class _Spec:
    code: str
    bucket: AdapterErrorBucket
    description: str


ADAPTER_ERROR_CATALOG: dict[str, _Spec] = {
    spec.code: spec
    for spec in (
        _Spec("ERR_ADAPT_K8S_TIMEOUT", AdapterErrorBucket.TRANSIENT,
              "Kubernetes API timeout while submitting/watching adapter Job"),
        _Spec("ERR_ADAPT_OOM", AdapterErrorBucket.TRANSIENT,
              "Adapter pod killed by OOM"),

        _Spec("ERR_ADAPT_NAMESPACE_FORBIDDEN", AdapterErrorBucket.CONFIGURABLE,
              "Worker SA cannot operate in adapter namespace"),
        _Spec("ERR_ADAPT_KVM_UNAVAILABLE", AdapterErrorBucket.CONFIGURABLE,
              "/dev/kvm not available — adapter falls back to TCG (slow). "
              "Configurable: enable nested virt or KVM device plugin."),

        _Spec("ERR_ADAPT_QCOW2_MISSING", AdapterErrorBucket.PERMANENT,
              "Source qcow2 not found on transit volume"),
        _Spec("ERR_ADAPT_GUEST_INSPECT_FAILED", AdapterErrorBucket.PERMANENT,
              "virt-inspector could not identify the guest OS"),
        _Spec("ERR_ADAPT_VIRT_CUSTOMIZE_FAILED", AdapterErrorBucket.PERMANENT,
              "virt-customize exited non-zero — fixup ops failed"),
        _Spec("ERR_ADAPT_INTERNAL", AdapterErrorBucket.PERMANENT,
              "Internal adapter error"),
    )
}


class AdapterError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        spec = ADAPTER_ERROR_CATALOG.get(code)
        if spec is None:
            spec = ADAPTER_ERROR_CATALOG["ERR_ADAPT_INTERNAL"]
            message = f"[unknown code {code!r}] {message}"
        self.code = spec.code
        self.bucket = spec.bucket
        self.message = message
        self.__cause__ = cause
        super().__init__(f"{self.code}: {message}")

    @property
    def is_retryable(self) -> bool:
        return self.bucket == AdapterErrorBucket.TRANSIENT
