"""
Routes API pour la gestion des Hypervisors

Endpoints CRUD pour les hyperviseurs sources (vSphere, VMware, Hyper-V, etc.)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from app.core.database import get_db
from app.api.deps import check_permission
from app.models.user import User
from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.schemas.hypervisor import (
    HypervisorCreate,
    HypervisorUpdate,
    HypervisorResponse,
    HypervisorListResponse,
    HypervisorTestConnection,
    HypervisorTestConnectionResponse
)
from app.services.discovery import create_discovery_service, DiscoveryError

router = APIRouter()


@router.get("", response_model=HypervisorListResponse)
def list_hypervisors(
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
        limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
        hypervisor_type: Annotated[
            Optional[HypervisorType], Query(alias="type", description="Filtrer par type")] = None,
        status_filter: Annotated[
            Optional[HypervisorStatus], Query(alias="status", description="Filtrer par statut")] = None,
        is_active: Annotated[Optional[bool], Query(description="Filtrer par état actif/inactif")] = None,
        search: Annotated[Optional[str], Query(description="Rechercher par nom ou host")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "read"))] = None
):
    """
    Liste tous les Hypervisors avec pagination et filtres.

    **Permissions requises :** hypervisors:read
    """
    # Construction de la requête
    query = db.query(Hypervisor)

    # Multi-tenancy isolation
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)

    # Filtres
    if hypervisor_type:
        query = query.filter(Hypervisor.type == hypervisor_type)

    if status_filter:
        query = query.filter(Hypervisor.status == status_filter)

    if is_active is not None:
        query = query.filter(Hypervisor.is_active == is_active)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Hypervisor.name.ilike(search_filter)) |
            (Hypervisor.host.ilike(search_filter))
        )

    # Total count
    total = query.count()

    # Pagination
    hypervisors = query.offset(skip).limit(limit).all()

    # Convertir en schémas Pydantic
    items = [HypervisorResponse.model_validate(h) for h in hypervisors]

    return HypervisorListResponse(
        total=total,
        items=items,
        page=(skip // limit) + 1,
        page_size=limit
    )


@router.post("", response_model=HypervisorResponse, status_code=status.HTTP_201_CREATED)
def create_hypervisor(
        hypervisor_data: HypervisorCreate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "create"))] = None
):
    """
    Crée un nouvel Hypervisor.

    **Permissions requises :** hypervisors:create

    ⚠️ Attention : Le mot de passe est stocké en clair pour le moment.
    TODO: Implémenter le chiffrement avec Fernet.
    """
    # Vérifier si un hypervisor avec le même nom existe déjà
    existing = db.query(Hypervisor).filter(
        Hypervisor.name == hypervisor_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Un hypervisor avec le nom '{hypervisor_data.name}' existe déjà"
        )

    # Créer l'hypervisor
    hypervisor = Hypervisor(
        **hypervisor_data.model_dump(exclude_unset=True),
        tenant_id=current_user.tenant_id,
        status=HypervisorStatus.UNKNOWN
    )

    db.add(hypervisor)
    db.commit()
    db.refresh(hypervisor)

    return HypervisorResponse.model_validate(hypervisor)


@router.get("/{hypervisor_id}", response_model=HypervisorResponse)
def get_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "read"))] = None
):
    """
    Récupère les détails d'un Hypervisor.

    **Permissions requises :** hypervisors:read
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)
    hypervisor = query.first()

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    return HypervisorResponse.model_validate(hypervisor)


@router.put("/{hypervisor_id}", response_model=HypervisorResponse)
def update_hypervisor(
        hypervisor_id: int,
        hypervisor_update: HypervisorUpdate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "update"))] = None
):
    """
    Met à jour un Hypervisor.

    **Permissions requises :** hypervisors:update
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)
    hypervisor = query.first()

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    # Appliquer les modifications
    update_data = hypervisor_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(hypervisor, field, value)

    db.commit()
    db.refresh(hypervisor)

    return HypervisorResponse.model_validate(hypervisor)


@router.delete("/{hypervisor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "delete"))] = None
):
    """
    Supprime un Hypervisor.

    **Permissions requises :** hypervisors:delete

    ⚠️ Attention : Les VMs associées auront leur source_hypervisor_id mis à NULL.
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)
    hypervisor = query.first()

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    db.delete(hypervisor)
    db.commit()

    return None


@router.get("/{hypervisor_id}/vms")
def get_hypervisor_vms(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "read"))] = None
):
    """
    Récupère toutes les VMs découvertes depuis cet hypervisor.

    **Permissions requises :** hypervisors:read, vms:read
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)
    hypervisor = query.first()

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    # Retourner les VMs associées
    from app.schemas.vm import VMResponse
    vms = [VMResponse.model_validate(vm) for vm in hypervisor.virtual_machines]

    return {
        "hypervisor_id": hypervisor_id,
        "hypervisor_name": hypervisor.name,
        "total_vms": len(vms),
        "vms": vms
    }


@router.post("/test-connection", response_model=HypervisorTestConnectionResponse)
def test_hypervisor_connection(
        test_data: HypervisorTestConnection,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "create"))] = None
):
    """
    Teste la connexion à un hypervisor avant de le créer.

    **Permissions requises :** hypervisors:create

    ⚠️ Note : Cette fonctionnalité nécessite l'implémentation des clients
    vSphere/VMware/Hyper-V. Pour l'instant, retourne un succès simulé.
    """
    # TODO: Implémenter la connexion réelle selon le type
    # - vSphere: utiliser pyvmomi
    # - VMware Workstation: utiliser vmrun
    # - Hyper-V: utiliser PowerShell via subprocess
    # - KVM: utiliser libvirt

    # Simulation pour le moment
    return HypervisorTestConnectionResponse(
        success=True,
        message=f"Connexion à {test_data.host} simulée avec succès (implémentation à venir)",
        vms_count=None,
        error=None
    )


@router.post("/{hypervisor_id}/sync")
def sync_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "update"))] = None
):
    """
    Synchronise les VMs depuis l'hypervisor.

    **Permissions requises :** hypervisors:update

    Lance une découverte des VMs sur l'hypervisor source.
    Utilise le Discovery Service pour scanner et importer les VMs.
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if not current_user.is_superuser:
        query = query.filter(Hypervisor.tenant_id == current_user.tenant_id)
    hypervisor = query.first()

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    # Lancer la découverte
    try:
        discovery_service = create_discovery_service(db)
        stats = discovery_service.discover_hypervisor(hypervisor_id)

        return {
            "hypervisor_id": hypervisor_id,
            "hypervisor_name": hypervisor.name,
            "status": "success",
            "message": "Découverte terminée avec succès",
            "statistics": {
                "total_discovered": stats["total_discovered"],
                "new_vms": stats["new_vms"],
                "updated_vms": stats["updated_vms"],
                "errors": stats["errors"]
            }
        }

    except DiscoveryError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la découverte: {str(e)}"
        )


@router.get("/stats/summary")
def get_hypervisors_stats(
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("hypervisors", "read"))] = None
):
    """
    Statistiques globales des hypervisors.

    **Permissions requises :** hypervisors:read
    """
    def _scoped_query():
        q = db.query(Hypervisor)
        if not current_user.is_superuser:
            q = q.filter(Hypervisor.tenant_id == current_user.tenant_id)
        return q

    total = _scoped_query().count()

    stats = {
        "total": total,
        "by_type": {},
        "by_status": {},
        "active": _scoped_query().filter(Hypervisor.is_active == True).count(),
        "inactive": _scoped_query().filter(Hypervisor.is_active == False).count()
    }

    # Par type
    for hyp_type in HypervisorType:
        count = _scoped_query().filter(Hypervisor.type == hyp_type).count()
        if count > 0:
            stats["by_type"][hyp_type.value] = count

    # Par statut
    for hyp_status in HypervisorStatus:
        count = _scoped_query().filter(Hypervisor.status == hyp_status).count()
        if count > 0:
            stats["by_status"][hyp_status.value] = count

    return stats