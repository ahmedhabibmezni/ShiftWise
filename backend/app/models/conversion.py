"""
Modèles Conversion — disque source vers QCOW2/RAW pour KubeVirt/CDI.

Trois tables :
- conversion_groups : un groupe par VM (un job par disque)
- conversion_jobs   : un disque source -> un disque cible
- conversion_attempts : audit (un row par essai, retry inclus)

Hand-off : status = READY -> Migrator peut consommer output_path.
"""

from sqlalchemy import (
    Column, String, Integer, BigInteger, DateTime, Text,
    Enum as SQLEnum, ForeignKey, JSON, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
import enum

from app.models.base import BaseModel


class ConversionGroupStatus(str, enum.Enum):
    """Statut agrégé d'un groupe de conversion (toutes les disques d'une VM)."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    PARTIAL = "partial"          # mix de READY + FAILED, opérateur peut retry
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversionStatus(str, enum.Enum):
    """Statut d'un job de conversion (un disque)."""
    PENDING = "pending"
    PLANNING = "planning"
    STAGING = "staging"           # pull depuis hyperviseur vers NFS
    CONVERTING = "converting"     # qemu-img / virt-v2v
    VERIFYING = "verifying"       # qemu-img info + check + sha256
    READY = "ready"               # prêt pour CDI
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    EXPIRED = "expired"           # output supprimé après TTL


class SourceFormat(str, enum.Enum):
    VMDK = "vmdk"
    VHD = "vhd"
    VHDX = "vhdx"
    QCOW2 = "qcow2"
    RAW = "raw"


class TargetFormat(str, enum.Enum):
    QCOW2 = "qcow2"
    RAW = "raw"


class ConversionTool(str, enum.Enum):
    QEMU_IMG = "qemu_img"
    VIRT_V2V = "virt_v2v"          # injection drivers virtio (Windows)
    PASSTHROUGH = "passthrough"    # déjà QCOW2, pas de conversion


# Statuts terminaux (no further transitions)
TERMINAL_JOB_STATUSES = frozenset({
    ConversionStatus.READY,
    ConversionStatus.FAILED,
    ConversionStatus.CANCELLED,
    ConversionStatus.EXPIRED,
})

# Statuts retryables (auto ou manuel)
RETRYABLE_JOB_STATUSES = frozenset({
    ConversionStatus.FAILED,
})


class ConversionGroup(BaseModel):
    """Groupe agrégeant les jobs de conversion d'une VM (un par disque)."""

    __tablename__ = "conversion_groups"

    tenant_id = Column(String(100), nullable=False, index=True)

    vm_id = Column(
        Integer,
        ForeignKey("virtual_machines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    migration_id = Column(
        Integer,
        ForeignKey("migrations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # UUID exposé en API (les IDs internes restent intégers)
    group_uuid = Column(String(36), nullable=False, unique=True, index=True)

    status = Column(
        SQLEnum(ConversionGroupStatus),
        nullable=False,
        default=ConversionGroupStatus.PENDING,
        index=True,
    )

    target_format = Column(
        SQLEnum(TargetFormat), nullable=False, default=TargetFormat.QCOW2,
    )

    # Config de pull (cold/warm, options par hyperviseur)
    pull_config = Column(JSON, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    error_message = Column(Text, nullable=True)

    # Relations
    jobs = relationship(
        "ConversionJob",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="ConversionJob.disk_index",
    )

    def __repr__(self):
        return (
            f"<ConversionGroup(id={self.id}, vm_id={self.vm_id}, "
            f"status={self.status.value}, jobs={len(self.jobs) if self.jobs else 0})>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "group_uuid": self.group_uuid,
            "tenant_id": self.tenant_id,
            "vm_id": self.vm_id,
            "migration_id": self.migration_id,
            "status": self.status.value,
            "target_format": self.target_format.value,
            "pull_config": self.pull_config,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "jobs_count": len(self.jobs) if self.jobs else 0,
        }


class ConversionJob(BaseModel):
    """Job de conversion d'un disque source vers un disque cible."""

    __tablename__ = "conversion_jobs"
    __table_args__ = (
        # Un disque par groupe — pas de doublons
        UniqueConstraint("group_id", "disk_index", name="uq_conversion_jobs_group_disk"),
        Index("ix_conversion_jobs_status_tenant", "status", "tenant_id"),
    )

    tenant_id = Column(String(100), nullable=False, index=True)

    group_id = Column(
        Integer,
        ForeignKey("conversion_groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vm_id = Column(
        Integer,
        ForeignKey("virtual_machines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    disk_index = Column(Integer, nullable=False)

    source_format = Column(SQLEnum(SourceFormat), nullable=False)
    target_format = Column(
        SQLEnum(TargetFormat), nullable=False, default=TargetFormat.QCOW2,
    )
    tool = Column(SQLEnum(ConversionTool), nullable=False)

    source_path = Column(String(512), nullable=True)
    staged_path = Column(String(512), nullable=True)
    output_path = Column(String(512), nullable=True)

    source_size_bytes = Column(BigInteger, nullable=True)
    output_size_bytes = Column(BigInteger, nullable=True)
    sha256 = Column(String(64), nullable=True)

    status = Column(
        SQLEnum(ConversionStatus),
        nullable=False,
        default=ConversionStatus.PENDING,
        index=True,
    )
    progress_pct = Column(Integer, nullable=False, default=0)

    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)

    error_code = Column(String(64), nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    celery_task_id = Column(String(64), nullable=True, index=True)
    k8s_job_name = Column(String(253), nullable=True)  # nom Job in-cluster

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    group = relationship("ConversionGroup", back_populates="jobs")
    attempt_log = relationship(
        "ConversionAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ConversionAttempt.attempt_number",
    )

    def __repr__(self):
        return (
            f"<ConversionJob(id={self.id}, group_id={self.group_id}, "
            f"disk={self.disk_index}, status={self.status.value})>"
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES

    @property
    def can_retry(self) -> bool:
        return (
            self.status in RETRYABLE_JOB_STATUSES
            and self.attempts < self.max_attempts
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "group_id": self.group_id,
            "vm_id": self.vm_id,
            "disk_index": self.disk_index,
            "source_format": self.source_format.value,
            "target_format": self.target_format.value,
            "tool": self.tool.value,
            "source_path": self.source_path,
            "staged_path": self.staged_path,
            "output_path": self.output_path,
            "source_size_bytes": self.source_size_bytes,
            "output_size_bytes": self.output_size_bytes,
            "sha256": self.sha256,
            "status": self.status.value,
            "progress_pct": self.progress_pct,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "k8s_job_name": self.k8s_job_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_terminal": self.is_terminal,
            "can_retry": self.can_retry,
        }


class ConversionAttempt(BaseModel):
    """Audit : un row par tentative (initiale + retries)."""

    __tablename__ = "conversion_attempts"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "attempt_number", name="uq_conversion_attempts_job_attempt",
        ),
    )

    job_id = Column(
        Integer,
        ForeignKey("conversion_jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    attempt_number = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    final_status = Column(SQLEnum(ConversionStatus), nullable=False)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    log_path = Column(String(512), nullable=True)
    tool_exit_code = Column(Integer, nullable=True)

    job = relationship("ConversionJob", back_populates="attempt_log")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "attempt_number": self.attempt_number,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "final_status": self.final_status.value,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "log_path": self.log_path,
            "tool_exit_code": self.tool_exit_code,
            "created_at": self.created_at.isoformat(),
        }
