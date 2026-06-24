"""
Schémas Pydantic pour la conversion de disques.
"""

from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict

from app.models.conversion import (
    ConversionGroupStatus,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)


# --- Création ---

class ConversionCreate(BaseModel):
    """Création d'un groupe de conversion pour une VM (un job par disque)."""
    vm_id: int = Field(..., description="ID de la VM à convertir")
    target_format: TargetFormat = Field(
        TargetFormat.QCOW2,
        description="Format cible (QCOW2 par défaut, RAW pour stockage block)",
    )
    cold: bool = Field(
        True,
        description="Pull à froid (VM arrêtée). False = pull à chaud (best-effort par hyperviseur)",
    )
    max_attempts: int = Field(3, ge=1, le=10)
    pull_options: Optional[dict] = Field(None, description="Options spécifiques connecteur")
    migration_id: Optional[int] = Field(
        None, description="Si lié à une migration (sinon standalone)",
    )


# --- Réponses ---

class ConversionAttemptResponse(BaseModel):
    id: int
    job_id: int
    attempt_number: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    final_status: ConversionStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    log_path: Optional[str] = None
    tool_exit_code: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversionJobResponse(BaseModel):
    id: int
    tenant_id: str
    group_id: int
    vm_id: int
    disk_index: int
    source_format: SourceFormat
    target_format: TargetFormat
    tool: ConversionTool
    source_path: Optional[str] = None
    staged_path: Optional[str] = None
    output_path: Optional[str] = None
    source_size_bytes: Optional[int] = None
    output_size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    status: ConversionStatus
    progress_pct: int
    attempts: int
    max_attempts: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    k8s_job_name: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    is_terminal: bool
    can_retry: bool

    model_config = ConfigDict(from_attributes=True)


class ConversionGroupResponse(BaseModel):
    id: int
    group_uuid: str
    tenant_id: str
    vm_id: int
    migration_id: Optional[int] = None
    status: ConversionGroupStatus
    target_format: TargetFormat
    pull_config: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    jobs: List[ConversionJobResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ConversionGroupListResponse(BaseModel):
    total: int
    items: List[ConversionGroupResponse]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)

    model_config = ConfigDict(from_attributes=True)  # Audit D10


# --- Actions ---

class ConversionCancel(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class ConversionRetry(BaseModel):
    """Retry uniquement les jobs FAILED du groupe."""
    reset_attempts: bool = Field(
        False,
        description="Réinitialise le compteur attempts (défaut: incrémente seulement)",
    )


# --- Stats ---

class ConversionStats(BaseModel):
    total_groups: int
    pending: int
    in_progress: int
    ready: int
    partial: int
    failed: int
    cancelled: int
    total_jobs: int
    total_bytes_converted: int
    average_duration_seconds: Optional[int] = None
