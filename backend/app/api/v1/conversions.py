"""
Routes API pour les conversions de disques (VMDK/VHD/VHDX → QCOW2/RAW).

Endpoints (ordre statique-avant-dynamique respecté) :
- POST   /vms/{vm_id}/convert        # entry point per-VM (vit dans vms.py)
- GET    /conversions                # liste paginée
- GET    /conversions/stats          # statistiques
- GET    /conversions/{group_uuid}   # détail
- POST   /conversions/{group_uuid}/cancel
- POST   /conversions/{group_uuid}/retry
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import check_permission
from app.core.database import get_db
from app.crud import conversion as crud_conversion
from app.models.conversion import ConversionGroupStatus, ConversionStatus
from app.models.user import User
from app.schemas.conversion import (
    ConversionCancel,
    ConversionGroupListResponse,
    ConversionGroupResponse,
    ConversionRetry,
    ConversionStats,
)

router = APIRouter()


_RES = "conversions"


def _tenant_or_none(user: User) -> Optional[str]:
    return None if user.is_superuser else user.tenant_id


# --- Static routes first ---

@router.get("", response_model=ConversionGroupListResponse)
def list_conversions(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    vm_id: Annotated[Optional[int], Query()] = None,
    status_filter: Annotated[Optional[ConversionGroupStatus], Query(alias="status")] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(_RES, "read"))] = None,
):
    """Liste paginée des groupes de conversion. Permissions : conversions:read."""
    tenant_id = _tenant_or_none(current_user)
    total = crud_conversion.count_groups(
        db, tenant_id=tenant_id, vm_id=vm_id, status=status_filter,
    )
    groups = crud_conversion.list_groups(
        db, skip=skip, limit=limit, tenant_id=tenant_id,
        vm_id=vm_id, status=status_filter,
    )
    items = [ConversionGroupResponse.model_validate(g) for g in groups]
    return ConversionGroupListResponse(
        total=total, items=items,
        page=(skip // limit) + 1, page_size=limit,
    )


@router.get("/stats", response_model=ConversionStats)
def conversion_stats(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(_RES, "read"))] = None,
):
    """Statistiques agrégées sur les groupes de conversion. Permissions : conversions:read."""
    tenant_id = _tenant_or_none(current_user)

    counts: dict[ConversionGroupStatus, int] = {}
    total_groups = 0
    for s in ConversionGroupStatus:
        c = crud_conversion.count_groups(db, tenant_id=tenant_id, status=s)
        counts[s] = c
        total_groups += c

    # Job-level totals — cheap aggregate over READY jobs.
    from sqlalchemy import func
    from app.models.conversion import ConversionJob
    q = db.query(
        func.count(ConversionJob.id),
        func.coalesce(func.sum(ConversionJob.output_size_bytes), 0),
    )
    if tenant_id is not None:
        q = q.filter(ConversionJob.tenant_id == tenant_id)
    total_jobs, total_bytes = q.one()

    return ConversionStats(
        total_groups=total_groups,
        pending=counts[ConversionGroupStatus.PENDING],
        in_progress=counts[ConversionGroupStatus.IN_PROGRESS],
        ready=counts[ConversionGroupStatus.READY],
        partial=counts[ConversionGroupStatus.PARTIAL],
        failed=counts[ConversionGroupStatus.FAILED],
        cancelled=counts[ConversionGroupStatus.CANCELLED],
        total_jobs=int(total_jobs or 0),
        total_bytes_converted=int(total_bytes or 0),
        average_duration_seconds=None,
    )


# --- Dynamic routes ---

@router.get("/{group_uuid}", response_model=ConversionGroupResponse)
def get_conversion(
    group_uuid: str,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(_RES, "read"))] = None,
):
    """Détail d'un groupe (incluant ses jobs). Permissions : conversions:read."""
    group = crud_conversion.get_group_by_uuid(
        db, group_uuid, tenant_id=_tenant_or_none(current_user),
    )
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversion group not found")
    return ConversionGroupResponse.model_validate(group)


@router.post("/{group_uuid}/cancel", response_model=ConversionGroupResponse)
def cancel_conversion(
    group_uuid: str,
    payload: ConversionCancel,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(_RES, "update"))] = None,
):
    """Annule un groupe et ses jobs in-flight. Permissions : conversions:update."""
    group = crud_conversion.get_group_by_uuid(
        db, group_uuid, tenant_id=_tenant_or_none(current_user),
    )
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversion group not found")
    if group.status in (
        ConversionGroupStatus.READY,
        ConversionGroupStatus.FAILED,
        ConversionGroupStatus.CANCELLED,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Group already in terminal state: {group.status.value}",
        )

    # Mark all in-flight jobs CANCELLED.
    for job in group.jobs:
        if job.status not in (
            ConversionStatus.READY,
            ConversionStatus.FAILED,
            ConversionStatus.CANCELLED,
            ConversionStatus.EXPIRED,
        ):
            crud_conversion.set_job_status(
                db, job.id, ConversionStatus.CANCELLED,
                error_message=payload.reason,
            )
    crud_conversion.recompute_group_status(db, group.id)
    crud_conversion.set_group_status(
        db, group.id, ConversionGroupStatus.CANCELLED, error_message=payload.reason,
    )
    db.refresh(group)
    return ConversionGroupResponse.model_validate(group)


@router.post("/{group_uuid}/retry", response_model=ConversionGroupResponse)
def retry_conversion(
    group_uuid: str,
    payload: ConversionRetry,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(_RES, "update"))] = None,
):
    """Re-enqueue les jobs FAILED d'un groupe (PARTIAL ou FAILED).

    Permissions : conversions:update.
    """
    group = crud_conversion.get_group_by_uuid(
        db, group_uuid, tenant_id=_tenant_or_none(current_user),
    )
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversion group not found")
    if group.status not in (
        ConversionGroupStatus.PARTIAL,
        ConversionGroupStatus.FAILED,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot retry group in state {group.status.value}",
        )

    retried_ids: list[int] = []
    for job in group.jobs:
        if job.status != ConversionStatus.FAILED:
            continue
        update = {"error_code": None, "error_message": None, "progress_pct": 0}
        if payload.reset_attempts:
            update["attempts"] = 0
        crud_conversion.update_job(db, job.id, update)
        crud_conversion.set_job_status(db, job.id, ConversionStatus.RETRYING)
        retried_ids.append(job.id)

    if not retried_ids:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No FAILED jobs to retry in this group",
        )

    crud_conversion.recompute_group_status(db, group.id)

    # Audit H-17 : enfiler effectivement les jobs relancés. Sans cet appel
    # ils restaient bloqués en RETRYING — aucun worker ne scrute ce statut.
    from app.tasks.conversion import run_conversion_job
    for job_id in retried_ids:
        run_conversion_job.delay(job_id)

    db.refresh(group)
    return ConversionGroupResponse.model_validate(group)
