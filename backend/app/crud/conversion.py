"""
CRUD pour les conversions (groupes + jobs + tentatives).

Filtrage multi-tenancy via tenant_id optionnel — laissé None pour les workers
internes qui agissent au nom de tous les tenants.
"""

from typing import Optional, List
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session

from app.models.conversion import (
    ConversionGroup,
    ConversionJob,
    ConversionAttempt,
    ConversionGroupStatus,
    ConversionStatus,
    ConversionTool,
    SourceFormat,
    TargetFormat,
)


# Champs protégés — modifiés uniquement par le worker
_GROUP_PROTECTED = {"status", "tenant_id", "vm_id", "group_uuid"}
_JOB_PROTECTED = {
    "status", "tenant_id", "group_id", "vm_id", "disk_index",
    "source_format", "tool",
}


# --- Group ---

def get_group(
    db: Session,
    group_id: int,
    tenant_id: Optional[str] = None,
) -> Optional[ConversionGroup]:
    q = db.query(ConversionGroup).filter(ConversionGroup.id == group_id)
    if tenant_id is not None:
        q = q.filter(ConversionGroup.tenant_id == tenant_id)
    return q.first()


def get_group_by_uuid(
    db: Session,
    group_uuid: str,
    tenant_id: Optional[str] = None,
) -> Optional[ConversionGroup]:
    q = db.query(ConversionGroup).filter(ConversionGroup.group_uuid == group_uuid)
    if tenant_id is not None:
        q = q.filter(ConversionGroup.tenant_id == tenant_id)
    return q.first()


def list_groups(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    tenant_id: Optional[str] = None,
    vm_id: Optional[int] = None,
    status: Optional[ConversionGroupStatus] = None,
) -> List[ConversionGroup]:
    q = db.query(ConversionGroup)
    if tenant_id is not None:
        q = q.filter(ConversionGroup.tenant_id == tenant_id)
    if vm_id is not None:
        q = q.filter(ConversionGroup.vm_id == vm_id)
    if status is not None:
        q = q.filter(ConversionGroup.status == status)
    return q.order_by(ConversionGroup.created_at.desc()).offset(skip).limit(limit).all()


def count_groups(
    db: Session,
    tenant_id: Optional[str] = None,
    vm_id: Optional[int] = None,
    status: Optional[ConversionGroupStatus] = None,
) -> int:
    q = db.query(ConversionGroup)
    if tenant_id is not None:
        q = q.filter(ConversionGroup.tenant_id == tenant_id)
    if vm_id is not None:
        q = q.filter(ConversionGroup.vm_id == vm_id)
    if status is not None:
        q = q.filter(ConversionGroup.status == status)
    return q.count()


def create_group(
    db: Session,
    tenant_id: str,
    vm_id: int,
    target_format: TargetFormat = TargetFormat.QCOW2,
    pull_config: Optional[dict] = None,
    migration_id: Optional[int] = None,
) -> ConversionGroup:
    group = ConversionGroup(
        tenant_id=tenant_id,
        vm_id=vm_id,
        migration_id=migration_id,
        group_uuid=str(uuid.uuid4()),
        status=ConversionGroupStatus.PENDING,
        target_format=target_format,
        pull_config=pull_config,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_group(
    db: Session,
    group_id: int,
    update_data: dict,
    tenant_id: Optional[str] = None,
) -> Optional[ConversionGroup]:
    group = get_group(db, group_id, tenant_id=tenant_id)
    if not group:
        return None
    for field, value in update_data.items():
        if field not in _GROUP_PROTECTED:
            setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return group


def set_group_status(
    db: Session,
    group_id: int,
    status: ConversionGroupStatus,
    error_message: Optional[str] = None,
) -> Optional[ConversionGroup]:
    """Setter privilégié pour le worker — bypass _GROUP_PROTECTED."""
    group = db.query(ConversionGroup).filter(ConversionGroup.id == group_id).first()
    if not group:
        return None
    now = datetime.now(timezone.utc)
    group.status = status
    if status == ConversionGroupStatus.IN_PROGRESS and not group.started_at:
        group.started_at = now
    if status in (
        ConversionGroupStatus.READY,
        ConversionGroupStatus.FAILED,
        ConversionGroupStatus.PARTIAL,
        ConversionGroupStatus.CANCELLED,
    ):
        group.completed_at = now
    if error_message is not None:
        group.error_message = error_message
    db.commit()
    db.refresh(group)
    return group


def recompute_group_status(
    db: Session,
    group_id: int,
) -> Optional[ConversionGroup]:
    """Recalcule le statut agrégé d'un groupe à partir des jobs enfants."""
    group = db.query(ConversionGroup).filter(ConversionGroup.id == group_id).first()
    if not group:
        return None

    statuses = [j.status for j in group.jobs]
    if not statuses:
        return group

    in_flight = {
        ConversionStatus.PENDING,
        ConversionStatus.PLANNING,
        ConversionStatus.STAGING,
        ConversionStatus.CONVERTING,
        ConversionStatus.VERIFYING,
        ConversionStatus.RETRYING,
    }
    # Audit E10 — EXPIRED (le Job K8s a dépassé son TTL avant d'aboutir) est
    # un état TERMINAL, agrégé comme un échec. Sans cela un groupe EXPIRED-only
    # tombait dans le `else` et restait IN_PROGRESS indéfiniment.
    terminal_fail = {ConversionStatus.FAILED, ConversionStatus.EXPIRED}
    has_in_flight = any(s in in_flight for s in statuses)
    has_ready = any(s == ConversionStatus.READY for s in statuses)
    has_failed = any(s in terminal_fail for s in statuses)
    has_cancelled = any(s == ConversionStatus.CANCELLED for s in statuses)

    if has_in_flight:
        new_status = ConversionGroupStatus.IN_PROGRESS
    elif all(s == ConversionStatus.READY for s in statuses):
        new_status = ConversionGroupStatus.READY
    elif has_ready and (has_failed or has_cancelled):
        new_status = ConversionGroupStatus.PARTIAL
    elif all(s in terminal_fail for s in statuses):
        new_status = ConversionGroupStatus.FAILED
    elif all(s == ConversionStatus.CANCELLED for s in statuses):
        new_status = ConversionGroupStatus.CANCELLED
    else:
        # Plus aucun job en vol : combinaison terminale non classée
        # (ex. CANCELLED + EXPIRED) — terminal, jamais IN_PROGRESS.
        new_status = ConversionGroupStatus.FAILED

    return set_group_status(db, group_id, new_status)


def delete_group(
    db: Session,
    group_id: int,
    tenant_id: Optional[str] = None,
) -> bool:
    group = get_group(db, group_id, tenant_id=tenant_id)
    if not group:
        return False
    if group.status == ConversionGroupStatus.IN_PROGRESS:
        raise ValueError("Impossible de supprimer un groupe en cours")
    db.delete(group)
    db.commit()
    return True


# --- Job ---

def get_job(
    db: Session,
    job_id: int,
    tenant_id: Optional[str] = None,
) -> Optional[ConversionJob]:
    q = db.query(ConversionJob).filter(ConversionJob.id == job_id)
    if tenant_id is not None:
        q = q.filter(ConversionJob.tenant_id == tenant_id)
    return q.first()


def list_jobs_for_group(
    db: Session,
    group_id: int,
    tenant_id: Optional[str] = None,
) -> List[ConversionJob]:
    q = db.query(ConversionJob).filter(ConversionJob.group_id == group_id)
    if tenant_id is not None:
        q = q.filter(ConversionJob.tenant_id == tenant_id)
    return q.order_by(ConversionJob.disk_index.asc()).all()


def create_job(
    db: Session,
    *,
    tenant_id: str,
    group_id: int,
    vm_id: int,
    disk_index: int,
    source_format: SourceFormat,
    target_format: TargetFormat,
    tool: ConversionTool,
    source_path: Optional[str] = None,
    source_size_bytes: Optional[int] = None,
    max_attempts: int = 3,
) -> ConversionJob:
    job = ConversionJob(
        tenant_id=tenant_id,
        group_id=group_id,
        vm_id=vm_id,
        disk_index=disk_index,
        source_format=source_format,
        target_format=target_format,
        tool=tool,
        source_path=source_path,
        source_size_bytes=source_size_bytes,
        max_attempts=max_attempts,
        status=ConversionStatus.PENDING,
        progress_pct=0,
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    db: Session,
    job_id: int,
    update_data: dict,
    tenant_id: Optional[str] = None,
) -> Optional[ConversionJob]:
    job = get_job(db, job_id, tenant_id=tenant_id)
    if not job:
        return None
    for field, value in update_data.items():
        if field not in _JOB_PROTECTED:
            setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


def set_job_status(
    db: Session,
    job_id: int,
    status: ConversionStatus,
    *,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    progress_pct: Optional[int] = None,
) -> Optional[ConversionJob]:
    """Setter privilégié pour le worker — bypass _JOB_PROTECTED."""
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        return None
    now = datetime.now(timezone.utc)
    job.status = status
    if status == ConversionStatus.STAGING and not job.started_at:
        job.started_at = now
    if status in (
        ConversionStatus.READY,
        ConversionStatus.FAILED,
        ConversionStatus.CANCELLED,
        ConversionStatus.EXPIRED,
    ):
        job.completed_at = now
    if error_code is not None:
        job.error_code = error_code
    if error_message is not None:
        job.error_message = error_message
    if progress_pct is not None:
        job.progress_pct = max(0, min(100, progress_pct))
    db.commit()
    db.refresh(job)
    return job


# --- Attempt audit ---

def create_attempt(
    db: Session,
    *,
    job_id: int,
    attempt_number: int,
    started_at: datetime,
) -> ConversionAttempt:
    attempt = ConversionAttempt(
        job_id=job_id,
        attempt_number=attempt_number,
        started_at=started_at,
        final_status=ConversionStatus.RETRYING,  # provisoire
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def finalize_attempt(
    db: Session,
    attempt_id: int,
    *,
    final_status: ConversionStatus,
    completed_at: datetime,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    log_path: Optional[str] = None,
    tool_exit_code: Optional[int] = None,
) -> Optional[ConversionAttempt]:
    attempt = (
        db.query(ConversionAttempt)
        .filter(ConversionAttempt.id == attempt_id)
        .first()
    )
    if not attempt:
        return None
    attempt.completed_at = completed_at
    attempt.final_status = final_status
    if attempt.started_at:
        # SQLite drops tzinfo on read even if it was written tz-aware —
        # normalise both sides to a common posture before subtracting.
        started = attempt.started_at
        end = completed_at
        if started.tzinfo is None and end.tzinfo is not None:
            started = started.replace(tzinfo=end.tzinfo)
        elif started.tzinfo is not None and end.tzinfo is None:
            end = end.replace(tzinfo=started.tzinfo)
        attempt.duration_seconds = int((end - started).total_seconds())
    if error_code is not None:
        attempt.error_code = error_code
    if error_message is not None:
        attempt.error_message = error_message
    if log_path is not None:
        attempt.log_path = log_path
    if tool_exit_code is not None:
        attempt.tool_exit_code = tool_exit_code
    db.commit()
    db.refresh(attempt)
    return attempt
