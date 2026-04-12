"""
Routes API pour la gestion des VirtualMachines

Endpoints CRUD pour les VMs découvertes et migrées.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from app.core.database import get_db
from app.api.deps import check_permission
from app.models.user import User
from app.models.virtual_machine import VMStatus, CompatibilityStatus
from app.schemas.vm import (
    VMCreate,
    VMUpdate,
    VMResponse,
    VMListResponse
)
from app.crud import vm as crud_vm

router = APIRouter()


@router.get("", response_model=VMListResponse)
def list_vms(
    skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
    status_filter: Annotated[Optional[VMStatus], Query(alias="status", description="Filtrer par statut")] = None,
    compatibility: Annotated[Optional[CompatibilityStatus], Query(description="Filtrer par compatibilité")] = None,
    hypervisor_id: Annotated[Optional[int], Query(description="Filtrer par hyperviseur source")] = None,
    search: Annotated[Optional[str], Query(description="Rechercher par nom, IP ou hostname")] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
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
    current_user: Annotated[User, Depends(check_permission("vms", "create"))] = None
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
        )

    return VMResponse.model_validate(vm)


# ---------------------------------------------------------------------------
# Routes statiques — DOIVENT être déclarées avant les routes dynamiques /{id}
# ---------------------------------------------------------------------------

@router.get("/stats/summary")
def get_vms_stats(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
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

    # Par statut
    for status_value in VMStatus:
        count = crud_vm.get_vms_count(db, tenant_id=tenant_id, status=status_value)
        stats["by_status"][status_value.value] = count

    # Par compatibilité
    for compat in CompatibilityStatus:
        count = crud_vm.get_vms_count(db, tenant_id=tenant_id, compatibility=compat)
        stats["by_compatibility"][compat.value] = count

    return stats


# ---------------------------------------------------------------------------
# Routes dynamiques /{vm_id}
# ---------------------------------------------------------------------------

@router.get("/{vm_id}", response_model=VMResponse)
def get_vm(
    vm_id: int,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
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
    current_user: Annotated[User, Depends(check_permission("vms", "update"))] = None
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
    current_user: Annotated[User, Depends(check_permission("vms", "delete"))] = None
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


@router.get("/{vm_id}/migrations")
def get_vm_migrations(
    vm_id: int,
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Récupère l'historique des migrations d'une VM.

    **Permissions requises :** vms:read, migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    # Retourner les migrations associées
    from app.schemas.migration import MigrationResponse
    migrations = [MigrationResponse.model_validate(m) for m in vm.migrations]

    return {
        "vm_id": vm_id,
        "vm_name": vm.name,
        "total_migrations": len(migrations),
        "migrations": migrations
    }
