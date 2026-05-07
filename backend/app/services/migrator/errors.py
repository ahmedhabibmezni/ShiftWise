"""
Error catalog for the Migrator stage.

Same three-bucket model as the converter (TRANSIENT / CONFIGURABLE /
PERMANENT). Codes are persisted on Migration.error_code and consumed by
the UI / metrics, so do not rename without a migration plan.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class MigratorErrorBucket(str, enum.Enum):
    TRANSIENT = "transient"
    CONFIGURABLE = "configurable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class _Spec:
    code: str
    bucket: MigratorErrorBucket
    description: str


MIGRATOR_ERROR_CATALOG: dict[str, _Spec] = {
    spec.code: spec
    for spec in (
        # Transient — auto-retry safe at the orchestrator level
        _Spec("ERR_MIG_K8S_TIMEOUT", MigratorErrorBucket.TRANSIENT,
              "Kubernetes API timeout"),
        _Spec("ERR_MIG_POPULATOR_OOM", MigratorErrorBucket.TRANSIENT,
              "Populator pod killed by OOM"),
        _Spec("ERR_MIG_PVC_PROVISIONING", MigratorErrorBucket.TRANSIENT,
              "Storage class slow to provision PVC"),

        # Configurable — operator action required
        _Spec("ERR_MIG_NAMESPACE_FORBIDDEN", MigratorErrorBucket.CONFIGURABLE,
              "Worker SA cannot operate in target namespace"),
        _Spec("ERR_MIG_STORAGE_CLASS_MISSING", MigratorErrorBucket.CONFIGURABLE,
              "Configured storage class does not exist"),
        _Spec("ERR_MIG_INSUFFICIENT_QUOTA", MigratorErrorBucket.CONFIGURABLE,
              "ResourceQuota or storage capacity exhausted"),
        _Spec("ERR_MIG_VM_NAME_CONFLICT", MigratorErrorBucket.CONFIGURABLE,
              "A VirtualMachine with the target name already exists"),

        # Permanent — never retry
        _Spec("ERR_MIG_QCOW2_MISSING", MigratorErrorBucket.PERMANENT,
              "Converter output is missing on transit volume"),
        _Spec("ERR_MIG_QCOW2_CORRUPT", MigratorErrorBucket.PERMANENT,
              "qemu-img convert refused source as corrupt"),
        _Spec("ERR_MIG_VM_CREATE_REJECTED", MigratorErrorBucket.PERMANENT,
              "KubeVirt rejected the VirtualMachine manifest"),
        _Spec("ERR_MIG_VMI_NEVER_RAN", MigratorErrorBucket.PERMANENT,
              "VirtualMachineInstance never reached Running phase"),
        _Spec("ERR_MIG_INTERNAL", MigratorErrorBucket.PERMANENT,
              "Internal migrator error"),
    )
}


class MigratorError(Exception):
    """Raised by migrator stages.

    The ``code`` MUST be a key of :data:`MIGRATOR_ERROR_CATALOG`. Unknown
    codes are coerced to ERR_MIG_INTERNAL (permanent) — fail loudly rather
    than silently retry.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        spec = MIGRATOR_ERROR_CATALOG.get(code)
        if spec is None:
            spec = MIGRATOR_ERROR_CATALOG["ERR_MIG_INTERNAL"]
            message = f"[unknown code {code!r}] {message}"
        self.code = spec.code
        self.bucket = spec.bucket
        self.message = message
        self.__cause__ = cause
        super().__init__(f"{self.code}: {message}")

    @property
    def is_retryable(self) -> bool:
        return self.bucket == MigratorErrorBucket.TRANSIENT
