"""
Routes API pour la gestion des VirtualMachines

Endpoints CRUD pour les VMs découvertes et migrées.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from app.core.database import get_db
from app.api.deps import get_current_user, check_permission
from app.models.user import User
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus
from app.schemas.vm import (
    VMCreate,
    VMUpdate,
    VMResponse,
    VMListResponse
)

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
    # Construction de la requête
    query = db.query(VirtualMachine)

    # Filtres
    if status_filter:
        query = query.filter(VirtualMachine.status == status_filter)

    if compatibility:
        query = query.filter(VirtualMachine.compatibility_status == compatibility)

    if hypervisor_id:
        query = query.filter(VirtualMachine.source_hypervisor_id == hypervisor_id)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (VirtualMachine.name.ilike(search_filter)) |
            (VirtualMachine.ip_address.ilike(search_filter)) |
            (VirtualMachine.hostname.ilike(search_filter))
        )

    # Total count
    total = query.count()

    # Pagination
    vms = query.offset(skip).limit(limit).all()

    # Convertir en schémas Pydantic
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
    # Vérifier si une VM avec le même nom existe déjà
    existing_vm = db.query(VirtualMachine).filter(
        VirtualMachine.name == vm_data.name
    ).first()

    if existing_vm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Une VM avec le nom '{vm_data.name}' existe déjà"
        )

    # Créer la VM
    vm = VirtualMachine(
        **vm_data.model_dump(exclude_unset=True),
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN
    )

    db.add(vm)
    db.commit()
    db.refresh(vm)

    return VMResponse.model_validate(vm)


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
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()

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
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    # Appliquer les modifications
    update_data = vm_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(vm, field, value)

    db.commit()
    db.refresh(vm)

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
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {vm_id} introuvable"
        )

    db.delete(vm)
    db.commit()

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
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()

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


@router.get("/stats/summary")
def get_vms_stats(
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Statistiques globales des VMs.

    **Permissions requises :** vms:read
    """
    total = db.query(VirtualMachine).count()

    stats = {
        "total": total,
        "by_status": {},
        "by_compatibility": {}
    }

    # Par statut
    for status_value in VMStatus:
        count = db.query(VirtualMachine).filter(
            VirtualMachine.status == status_value
        ).count()
        stats["by_status"][status_value.value] = count

    # Par compatibilité
    for compat in CompatibilityStatus:
        count = db.query(VirtualMachine).filter(
            VirtualMachine.compatibility_status == compat
        ).count()
        stats["by_compatibility"][compat.value] = count

    return stats