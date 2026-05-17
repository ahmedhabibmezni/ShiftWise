"""
Routes API pour la gestion des Hypervisors

Endpoints CRUD pour les hyperviseurs sources (vSphere, VMware, Hyper-V, etc.)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Annotated, Optional

from app.core.config import settings
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
from app.crud import hypervisor as crud_hypervisor
from app.schemas.vm import VMResponse
from app.models.virtual_machine import VirtualMachine, VMStatus

logger = logging.getLogger(__name__)

router = APIRouter()

# Audit I / S1192 — resource literal reused across the router.
RESOURCE_HYPERVISORS = "hypervisors"

# Audit B21 / H — rate-limit budget for POST /hypervisors/test-connection.
# The endpoint drives an outbound connection with caller-supplied host +
# credentials: an unthrottled credential/SSRF oracle. The window reuses the
# login-throttle window so a single knob governs both abuse surfaces.
_TEST_CONNECTION_MAX_PER_WINDOW = 10
_TEST_CONNECTION_RL_PREFIX = "rl:hv-test:"


def _test_connection_rate_limited(user_id: int) -> bool:
    """Return True when the caller has exhausted its test-connection budget.

    Redis-backed fixed-window counter, keyed per user. Fails OPEN: if Redis
    is unreachable the call is allowed (availability over a best-effort
    abuse control) and the failure is logged.
    """
    if _TEST_CONNECTION_MAX_PER_WINDOW <= 0:
        return False
    try:
        from app.core.redis_client import get_redis
        redis = get_redis()
        key = f"{_TEST_CONNECTION_RL_PREFIX}{user_id}"
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, settings.LOGIN_THROTTLE_WINDOW_SECONDS)
        return count > _TEST_CONNECTION_MAX_PER_WINDOW
    except Exception:
        logger.warning(
            "test-connection rate limiter unavailable (Redis down?) — "
            "allowing the request"
        )
        return False


class HypervisorSyncResponse(BaseModel):
    """Réponse de POST /hypervisors/{id}/sync (Audit C11).

    La découverte est une opération longue : l'endpoint répond 202 Accepted
    avec ce schéma plutôt qu'un 200 + dict libre.
    """
    hypervisor_id: int
    hypervisor_name: str
    status: str
    message: str
    total_discovered: int = 0
    new_vms: int = 0
    updated_vms: int = 0
    archived_vms: int = 0
    errors: int = 0


class HypervisorVMsResponse(BaseModel):
    """Réponse paginée de GET /hypervisors/{id}/vms (Audit C8 / C19)."""
    hypervisor_id: int
    hypervisor_name: str
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    vms: list[VMResponse]


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
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "read"))] = None
):
    """
    Liste tous les Hypervisors avec pagination et filtres.

    **Permissions requises :** hypervisors:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_hypervisor.get_hypervisors_count(
        db, tenant_id=tenant_id, hypervisor_type=hypervisor_type,
        status=status_filter, is_active=is_active, search=search
    )
    hypervisors = crud_hypervisor.get_hypervisors(
        db, skip=skip, limit=limit, tenant_id=tenant_id,
        hypervisor_type=hypervisor_type, status=status_filter,
        is_active=is_active, search=search
    )

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
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "create"))] = None
):
    """
    Crée un nouvel Hypervisor.

    **Permissions requises :** hypervisors:create

    ⚠️ Attention : Le mot de passe est stocké en clair pour le moment.
    TODO: Implémenter le chiffrement avec Fernet.
    """
    try:
        hypervisor = crud_hypervisor.create_hypervisor(
            db,
            data=hypervisor_data.model_dump(exclude_unset=True),
            tenant_id=current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    return HypervisorResponse.model_validate(hypervisor)


# ---------------------------------------------------------------------------
# Routes statiques — DOIVENT être déclarées avant les routes dynamiques /{id}
# ---------------------------------------------------------------------------

@router.get("/stats/summary")
def get_hypervisors_stats(
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "read"))] = None
):
    """
    Statistiques globales des hypervisors.

    **Permissions requises :** hypervisors:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_hypervisor.get_hypervisors_count(db, tenant_id=tenant_id)
    active = crud_hypervisor.get_hypervisors_count(
        db, tenant_id=tenant_id, is_active=True
    )

    # Single GROUP BY per column instead of 10+7 individual COUNTs. Guards
    # against Postgres enum drift: if a Python-side enum value (e.g. OVIRT)
    # is missing from the DB enum, a per-value SELECT explodes with
    # InvalidTextRepresentation. The GROUP BY only returns values that
    # actually appear in rows, so the failure mode is moot.
    by_type_query = db.query(
        Hypervisor.type, func.count(Hypervisor.id)
    ).group_by(Hypervisor.type)
    by_status_query = db.query(
        Hypervisor.status, func.count(Hypervisor.id)
    ).group_by(Hypervisor.status)
    if tenant_id is not None:
        by_type_query = by_type_query.filter(Hypervisor.tenant_id == tenant_id)
        by_status_query = by_status_query.filter(Hypervisor.tenant_id == tenant_id)

    return {
        "total": total,
        "active": active,
        "inactive": total - active,
        "by_type": {t.value: c for t, c in by_type_query.all() if c > 0},
        "by_status": {s.value: c for s, c in by_status_query.all() if c > 0},
    }


@router.post("/test-connection", response_model=HypervisorTestConnectionResponse)
def test_hypervisor_connection(
        test_data: HypervisorTestConnection,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "create"))] = None
):
    """
    Teste la connexion à un hypervisor avant de le créer.

    **Permissions requises :** hypervisors:create

    Reuses the discovery service connectors to enumerate VMs on the source
    without persisting anything. VSPHERE returns success=False until the
    pyvmomi-based connector lands.
    """
    # Audit B21 — l'endpoint pilote une connexion sortante avec un hôte et
    # des credentials fournis par l'appelant : oracle de credential / SSRF.
    # On le throttle par utilisateur.
    if _test_connection_rate_limited(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tests de connexion — réessayez plus tard.",
        )
    transient = Hypervisor(
        name="connection-test",
        tenant_id=current_user.tenant_id,
        type=test_data.type,
        host=test_data.host,
        port=test_data.port,
        username=test_data.username,
        password=test_data.password,
        verify_ssl=test_data.verify_ssl,
    )
    service = create_discovery_service(db)
    result = service.test_connection(transient)

    if result["success"]:
        message = f"Connexion réussie · {result['vms_count']} VMs détectées"
    else:
        message = "Échec de la connexion"

    return HypervisorTestConnectionResponse(
        success=result["success"],
        message=message,
        vms_count=result["vms_count"],
        error=result["error"],
    )


# ---------------------------------------------------------------------------
# Routes dynamiques /{hypervisor_id}
# ---------------------------------------------------------------------------

@router.get("/{hypervisor_id}", response_model=HypervisorResponse)
def get_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "read"))] = None
):
    """
    Récupère les détails d'un Hypervisor.

    **Permissions requises :** hypervisors:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    hypervisor = crud_hypervisor.get_hypervisor(db, hypervisor_id, tenant_id=tenant_id)

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
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "update"))] = None
):
    """
    Met à jour un Hypervisor.

    **Permissions requises :** hypervisors:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    update_data = hypervisor_update.model_dump(exclude_unset=True)
    hypervisor = crud_hypervisor.update_hypervisor(db, hypervisor_id, update_data, tenant_id=tenant_id)

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    return HypervisorResponse.model_validate(hypervisor)


@router.delete("/{hypervisor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "delete"))] = None
):
    """
    Supprime un Hypervisor.

    **Permissions requises :** hypervisors:delete

    ⚠️ Attention : Les VMs associées auront leur source_hypervisor_id mis à NULL
    (SET NULL). Les migrations en cours sur ces VMs deviennent orphelines.
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    deleted = crud_hypervisor.delete_hypervisor(db, hypervisor_id, tenant_id=tenant_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    return None


@router.get("/{hypervisor_id}/vms", response_model=HypervisorVMsResponse)
def get_hypervisor_vms(
        hypervisor_id: int,
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
        limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "read"))] = None,
        _vms_read: Annotated[User, Depends(check_permission("vms", "read"))] = None,
):
    """
    Récupère les VMs découvertes depuis cet hypervisor (paginé).

    **Permissions requises :** hypervisors:read ET vms:read (Audit B12).
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    hypervisor = crud_hypervisor.get_hypervisor(db, hypervisor_id, tenant_id=tenant_id)

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    # Audit C8 — pagination au niveau de la requête : on ne charge plus
    # toute la relation `virtual_machines` en mémoire.
    base = db.query(VirtualMachine).filter(
        VirtualMachine.source_hypervisor_id == hypervisor_id,
        VirtualMachine.status != VMStatus.ARCHIVED,
    )
    total = base.count()
    rows = base.order_by(VirtualMachine.id).offset(skip).limit(limit).all()
    vms = [VMResponse.model_validate(vm) for vm in rows]

    return {
        "hypervisor_id": hypervisor_id,
        "hypervisor_name": hypervisor.name,
        "total": total,
        "page": (skip // limit) + 1,
        "page_size": limit,
        "vms": vms,
    }


@router.post(
    "/{hypervisor_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=HypervisorSyncResponse,
)
def sync_hypervisor(
        hypervisor_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_HYPERVISORS, "update"))] = None
):
    """
    Synchronise les VMs depuis l'hypervisor.

    **Permissions requises :** hypervisors:update

    Lance une découverte des VMs sur l'hypervisor source. Opération longue —
    répond 202 Accepted avec un schéma typé (Audit C11).
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    hypervisor = crud_hypervisor.get_hypervisor(db, hypervisor_id, tenant_id=tenant_id)

    if not hypervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypervisor avec l'ID {hypervisor_id} introuvable"
        )

    # Lancer la découverte
    try:
        discovery_service = create_discovery_service(db)
        stats = discovery_service.discover_hypervisor(hypervisor_id)

        return HypervisorSyncResponse(
            hypervisor_id=hypervisor_id,
            hypervisor_name=hypervisor.name,
            status="success",
            message="Découverte terminée avec succès",
            total_discovered=stats["total_discovered"],
            new_vms=stats["new_vms"],
            updated_vms=stats["updated_vms"],
            archived_vms=stats.get("archived_vms", 0),
            errors=stats["errors"],
        )

    except DiscoveryError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la découverte: {str(e)}"
        )
