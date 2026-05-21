"""
Routes API pour la gestion des VirtualMachines

Endpoints CRUD pour les VMs découvertes et migrées.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from app.core.database import get_db
from app.api.deps import check_permission
from app.models.user import User
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus
from app.models.conversion import ConversionGroupStatus, ConversionStatus
from app.schemas.vm import (
    VMCreate,
    VMUpdate,
    VMResponse,
    VMListResponse
)
from app.schemas.migration import MigrationResponse
from app.crud import vm as crud_vm
from app.schemas.conversion import ConversionCreate, ConversionGroupResponse
from app.services.analyzer import create_analyzer_service
from app.services.converter.errors import ConversionError
from app.services.converter.service import create_converter_service
from app.crud import conversion as crud_conversion
from app.tasks.conversion import run_conversion_job  # Audit C18 — import module-level
from pydantic import BaseModel, Field

router = APIRouter()

# S1192 — resource literal reused across the router.
RESOURCE_VMS = "vms"


class VMAnalyzeBatchRequest(BaseModel):
    """Corps de POST /vms/analyze/batch (Audit C9 / C17).

    Les vm_ids arrivent dans le corps JSON, plus en query param : un client
    qui envoyait un body JSON était jusque-là silencieusement ignoré.
    """
    vm_ids: list[int] = Field(default_factory=list, description="VM IDs à analyser")


class VMMigrationsResponse(BaseModel):
    """Réponse paginée de GET /vms/{id}/migrations (Audit C8 / C19)."""
    vm_id: int
    vm_name: str
    total_migrations: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    migrations: list[MigrationResponse]


@router.get("", response_model=VMListResponse)
def list_vms(
    skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
    status_filter: Annotated[Optional[VMStatus], Query(alias="status", description="Filtrer par statut")] = None,
    compatibility: Annotated[Optional[CompatibilityStatus], Query(description="Filtrer par compatibilité")] = None,
    hypervisor_id: Annotated[Optional[int], Query(description="Filtrer par hyperviseur source")] = None,
    search: Annotated[Optional[str], Query(description="Rechercher par nom, IP ou hostname")] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "read"))] = None
):
    """
    Liste toutes les VirtualMachines avec pagination et filtres.

    **Permissions requises :** vms:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_vm.get_vms_count(
        db, tenant_id=tenant_id, status=status_filter,
        compatibility=compatibility, hypervisor_id=hypervisor_id, search=search
    )
    vms = crud_vm.get_vms(
        db, skip=skip, limit=limit, tenant_id=tenant_id,
        status=status_filter, compatibility=compatibility,
        hypervisor_id=hypervisor_id, search=search
    )

    items = [VMResponse.model_validate(vm) for vm in vms]

    return VMListResponse(
        total=total,
        items=items,
        page=(skip // limit) + 1,
        page_size=limit
    )


@router.post("", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
def create_vm(
    vm_data: VMCreate,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "create"))] = None
):
    """
    Crée une nouvelle VirtualMachine.

    **Permissions requises :** vms:create
    """
    try:
        vm = crud_vm.create_vm(
            db,
            data=vm_data.model_dump(exclude_unset=True),
            tenant_id=current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        ) from None

    return VMResponse.model_validate(vm)


# ---------------------------------------------------------------------------
# Routes statiques — DOIVENT être déclarées avant les routes dynamiques /{id}
# ---------------------------------------------------------------------------

@router.get("/stats/summary")
def get_vms_stats(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "read"))] = None
):
    """
    Statistiques globales des VMs.

    **Permissions requises :** vms:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_vm.get_vms_count(db, tenant_id=tenant_id)

    stats = {
        "total": total,
        "by_status": {},
        "by_compatibility": {}
    }

    # Par statut — single GROUP BY query (replaces 9 individual COUNT queries)
    by_status = {s.value: 0 for s in VMStatus}
    status_query = db.query(
        VirtualMachine.status,
        func.count(VirtualMachine.id)
    ).group_by(VirtualMachine.status)
    if tenant_id is not None:
        status_query = status_query.filter(VirtualMachine.tenant_id == tenant_id)
    for row_status, count in status_query.all():
        by_status[row_status.value] = count
    stats["by_status"] = by_status

    # Par compatibilité — single GROUP BY query (replaces 4 individual COUNT queries)
    by_compat = {c.value: 0 for c in CompatibilityStatus}
    compat_query = db.query(
        VirtualMachine.compatibility_status,
        func.count(VirtualMachine.id)
    ).group_by(VirtualMachine.compatibility_status)
    if tenant_id is not None:
        compat_query = compat_query.filter(VirtualMachine.tenant_id == tenant_id)
    for row_compat, count in compat_query.all():
        by_compat[row_compat.value] = count
    stats["by_compatibility"] = by_compat

    return stats


@router.get("/analyze/stats")
def get_compatibility_stats(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "read"))] = None
):
    """
    Compatibility analysis statistics.

    **Permissions requises :** vms:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    analyzer = create_analyzer_service()
    return analyzer.get_stats(db, tenant_id=tenant_id)


@router.post("/analyze/batch")
def analyze_vms_batch(
    payload: VMAnalyzeBatchRequest,
    force: Annotated[bool, Query(description="Re-analyze already-classified VMs")] = False,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "update"))] = None
):
    """
    Analyze multiple VMs (batch, synchronous, capped at 20).

    Les vm_ids arrivent dans le corps JSON (Audit C9). Au-delà de 20 : 422.

    **Permissions requises :** vms:update
    """
    vm_ids = payload.vm_ids
    if len(vm_ids) > 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Batch cap exceeded: {len(vm_ids)} > 20 (use Celery for async batch)"
        )
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    # Filter VM IDs by tenant (unless superuser)
    if tenant_id:
        accessible_ids = {
            row[0]
            for row in db.query(VirtualMachine.id)
            .filter(VirtualMachine.tenant_id == tenant_id, VirtualMachine.id.in_(vm_ids))
            .all()
        }
        vm_ids = [vid for vid in vm_ids if vid in accessible_ids]
    analyzer = create_analyzer_service()
    result = analyzer.analyze_batch(db, vm_ids[:20], force=force)
    return result


# ---------------------------------------------------------------------------
# Routes dynamiques /{vm_id}
# ---------------------------------------------------------------------------

@router.get("/{vm_id}", response_model=VMResponse)
def get_vm(
    vm_id: int,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "read"))] = None
):
    """
    Récupère les détails d'une VirtualMachine.

    **Permissions requises :** vms:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    return VMResponse.model_validate(vm)


@router.put("/{vm_id}", response_model=VMResponse)
def update_vm(
    vm_id: int,
    vm_update: VMUpdate,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "update"))] = None
):
    """
    Met à jour une VirtualMachine.

    **Permissions requises :** vms:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    update_data = vm_update.model_dump(exclude_unset=True)
    vm = crud_vm.update_vm(db, vm_id, update_data, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    return VMResponse.model_validate(vm)


@router.delete("/{vm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vm(
    vm_id: int,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "delete"))] = None
):
    """
    Supprime une VirtualMachine.

    **Permissions requises :** vms:delete

    ⚠️ Attention : Supprime également toutes les migrations associées.
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    deleted = crud_vm.delete_vm(db, vm_id, tenant_id=tenant_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    return None


@router.post("/{vm_id}/analyze", response_model=dict)
def analyze_single_vm(
    vm_id: int,
    force: Annotated[bool, Query(description="Re-analyze already-classified VMs")] = False,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "update"))] = None
):
    """
    Analyze a single VM's compatibility.

    By default, skips VMs already classified (status != UNKNOWN). Pass `?force=true`
    to re-analyze regardless of current compatibility_status.

    **Permissions requises :** vms:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    analyzer = create_analyzer_service()
    result = analyzer.analyze_vm(db, vm_id, force=force)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de l'analyse de la VM"
        )

    return result


@router.post(
    "/{vm_id}/convert",
    response_model=ConversionGroupResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def convert_vm(
    vm_id: int,
    payload: ConversionCreate,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("conversions", "create"))] = None,
):
    """Crée un groupe de conversion pour une VM (un job par disque source).

    Le travail effectif (pull + qemu-img/virt-v2v) est déclenché par le worker
    Celery — cet endpoint retourne 202 Accepted avec le groupe et ses jobs en
    statut PENDING.

    **Permissions requises :** conversions:create
    """
    if payload.vm_id != vm_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "vm_id in path and body must match",
        )

    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "User has no tenant_id",
        )

    vm = crud_vm.get_vm(
        db, vm_id, tenant_id=None if current_user.is_superuser else tenant_id,
    )
    if vm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"VM {vm_id} not found")

    # Audit B6 — si la conversion est rattachée à une migration, cette
    # migration DOIT appartenir au tenant de l'appelant, sinon IDOR
    # (un tenant référencerait la migration d'un autre).
    if payload.migration_id is not None:
        from app.crud import migration as crud_migration
        linked = crud_migration.get_migration(
            db, payload.migration_id,
            tenant_id=None if current_user.is_superuser else tenant_id,
        )
        if linked is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Migration {payload.migration_id} not found",
            )

    converter = create_converter_service()
    try:
        group_id = converter.create_group_for_vm(
            db,
            tenant_id=vm.tenant_id,
            vm_id=vm_id,
            target_format=payload.target_format,
            cold=payload.cold,
            pull_options=payload.pull_options,  # Audit C14 — n'est plus ignoré
            max_attempts=payload.max_attempts,
            migration_id=payload.migration_id,
        )
    except ConversionError as e:
        # Map permanent/configurable errors onto 4xx, transient onto 503.
        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if e.bucket.value == "transient"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(http_status, f"{e.code}: {e.message}") from e

    # Enqueue one Celery task per disk job. Workers pull from the
    # ``conversions`` queue and drive each job to a terminal state.
    # (run_conversion_job est importé au niveau module — Audit C18.)
    group = crud_conversion.get_group(db, group_id)
    try:
        for job in group.jobs:
            run_conversion_job.delay(job.id)
    except Exception as exc:
        # Audit H-18 : broker injoignable — basculer le groupe et ses jobs en
        # FAILED pour qu'ils ne restent pas bloqués en PENDING sans tâche
        # (le groupe redevient ainsi re-déclenchable via /conversions/{uuid}/retry).
        for job in group.jobs:
            crud_conversion.set_job_status(
                db, job.id, ConversionStatus.FAILED,
                error_message="Broker de tâches indisponible",
            )
        crud_conversion.set_group_status(
            db, group_id, ConversionGroupStatus.FAILED,
            error_message="Broker de tâches indisponible",
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Le broker de tâches est indisponible — conversion non démarrée, réessayez.",
        ) from exc

    db.refresh(group)
    return ConversionGroupResponse.model_validate(group)


@router.get("/{vm_id}/migrations", response_model=VMMigrationsResponse)
def get_vm_migrations(
    vm_id: int,
    skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, "read"))] = None,
    _migrations_read: Annotated[User, Depends(check_permission("migrations", "read"))] = None,
):
    """
    Historique paginé des migrations d'une VM.

    **Permissions requises :** vms:read ET migrations:read (Audit B11).
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    # Audit C8 — pagination au niveau de la requête (plus de chargement
    # complet de la relation `migrations` en mémoire).
    from app.models.migration import Migration
    base = db.query(Migration).filter(Migration.vm_id == vm_id)
    total = base.count()
    rows = base.order_by(Migration.id.desc()).offset(skip).limit(limit).all()
    migrations = [MigrationResponse.model_validate(m) for m in rows]

    return VMMigrationsResponse(
        vm_id=vm_id,
        vm_name=vm.name,
        total_migrations=total,
        page=(skip // limit) + 1,
        page_size=limit,
        migrations=migrations,
    )
