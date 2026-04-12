"""
Routes API pour la gestion des Migrations

Endpoints CRUD pour les migrations de VMs.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Annotated, Optional

from app.core.database import get_db
from app.api.deps import check_permission
from app.models.user import User
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.schemas.migration import (
    MigrationCancel,
    MigrationCreate,
    MigrationUpdate,
    MigrationProgressUpdate,
    MigrationResponse,
    MigrationListResponse,
    MigrationStats
)
from app.crud import migration as crud_migration
from app.crud import vm as crud_vm

router = APIRouter()


@router.get("", response_model=MigrationListResponse)
def list_migrations(
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
        limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
        status_filter: Annotated[
            Optional[MigrationStatus], Query(alias="status", description="Filtrer par statut")] = None,
        strategy: Annotated[Optional[MigrationStrategy], Query(description="Filtrer par stratégie")] = None,
        vm_id: Annotated[Optional[int], Query(description="Filtrer par VM")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "read"))] = None
):
    """
    Liste toutes les Migrations avec pagination et filtres.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=status_filter,
        strategy=strategy, vm_id=vm_id
    )
    migrations = crud_migration.get_migrations(
        db, skip=skip, limit=limit, tenant_id=tenant_id,
        status=status_filter, strategy=strategy, vm_id=vm_id
    )

    items = [MigrationResponse.model_validate(m) for m in migrations]

    return MigrationListResponse(
        total=total,
        items=items,
        page=(skip // limit) + 1,
        page_size=limit
    )


@router.post("", response_model=MigrationResponse, status_code=status.HTTP_201_CREATED)
def create_migration(
        migration_data: MigrationCreate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "create"))] = None
):
    """
    Crée une nouvelle Migration.

    **Permissions requises :** migrations:create
    """
    # Vérifier que la VM existe (et appartient au tenant de l'utilisateur)
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, migration_data.vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {migration_data.vm_id} introuvable"
        )

    # Vérifier que la VM peut être migrée
    if not vm.can_migrate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La VM '{vm.name}' ne peut pas être migrée (statut: {vm.status.value}, compatibilité: {vm.compatibility_status.value})"
        )

    # Créer la migration — namespace imposé par le tenant, non configurable par le client
    migration = crud_migration.create_migration(
        db,
        data=migration_data.model_dump(exclude_unset=True),
        tenant_id=current_user.tenant_id,
        target_namespace=f"shiftwise-{current_user.tenant_id}"
    )

    return MigrationResponse.model_validate(migration)


# ---------------------------------------------------------------------------
# Routes statiques — DOIVENT être déclarées avant les routes dynamiques /{id}
# ---------------------------------------------------------------------------

@router.get("/stats/summary", response_model=MigrationStats)
def get_migrations_stats(
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "read"))] = None
):
    """
    Statistiques globales des migrations.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_migration.get_migrations_count(db, tenant_id=tenant_id)
    completed = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.COMPLETED
    )
    failed = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.FAILED
    )
    pending = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.PENDING
    )
    cancelled = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.CANCELLED
    )
    rollback = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.ROLLBACK
    )
    rolled_back = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.ROLLED_BACK
    )
    in_progress = total - completed - failed - pending - cancelled - rollback - rolled_back

    # Taux de succès
    success_rate = (completed / total * 100) if total > 0 else 0.0

    # Durée moyenne (migrations terminées)
    completed_migrations = crud_migration.get_migrations(
        db, tenant_id=tenant_id, status=MigrationStatus.COMPLETED,
        skip=0, limit=10000
    )

    avg_duration = None
    if completed_migrations:
        total_duration = sum(m.duration_seconds for m in completed_migrations)
        avg_duration = int(total_duration / len(completed_migrations))

    # Total données transférées — scopé par tenant
    total_transferred_query = db.query(func.sum(Migration.transferred_gb))
    if tenant_id is not None:
        total_transferred_query = total_transferred_query.filter(
            Migration.tenant_id == tenant_id
        )
    total_transferred = total_transferred_query.scalar() or 0.0

    return MigrationStats(
        total_migrations=total,
        completed=completed,
        failed=failed,
        in_progress=in_progress,
        pending=pending,
        success_rate=success_rate,
        average_duration_seconds=avg_duration,
        total_data_transferred_gb=float(total_transferred)
    )


# ---------------------------------------------------------------------------
# Routes dynamiques /{migration_id}
# ---------------------------------------------------------------------------

@router.get("/{migration_id}", response_model=MigrationResponse)
def get_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "read"))] = None
):
    """
    Récupère les détails d'une Migration.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return MigrationResponse.model_validate(migration)


@router.put("/{migration_id}", response_model=MigrationResponse)
def update_migration(
        migration_id: int,
        migration_update: MigrationUpdate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "update"))] = None
):
    """
    Met à jour une Migration.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    update_data = migration_update.model_dump(exclude_unset=True)
    migration = crud_migration.update_migration(db, migration_id, update_data, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return MigrationResponse.model_validate(migration)


@router.delete("/{migration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "delete"))] = None
):
    """
    Supprime une Migration.

    **Permissions requises :** migrations:delete
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    try:
        deleted = crud_migration.delete_migration(db, migration_id, tenant_id=tenant_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return None


@router.post("/{migration_id}/start", response_model=MigrationResponse)
def start_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "update"))] = None
):
    """
    Démarre une migration.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    if migration.status != MigrationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La migration ne peut être démarrée (statut actuel: {migration.status.value})"
        )

    # Marquer comme démarrée
    migration.mark_started()

    db.commit()
    db.refresh(migration)

    # TODO: Déclencher le processus de migration asynchrone

    return MigrationResponse.model_validate(migration)


@router.post("/{migration_id}/cancel", response_model=MigrationResponse)
def cancel_migration(
        migration_id: int,
        cancel_data: MigrationCancel = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "update"))] = None
):
    """
    Annule une migration en cours.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    if not migration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La migration n'est pas en cours"
        )

    # Annuler
    migration.status = MigrationStatus.CANCELLED
    migration.completed_at = datetime.now(timezone.utc)
    migration.success = False
    migration.error_message = (cancel_data.reason if cancel_data and cancel_data.reason
                               else "Annulée par l'utilisateur")

    db.commit()
    db.refresh(migration)

    return MigrationResponse.model_validate(migration)


@router.put("/{migration_id}/progress", response_model=MigrationResponse)
def update_migration_progress(
        migration_id: int,
        progress: MigrationProgressUpdate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "update"))] = None
):
    """
    Met à jour la progression d'une migration.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    # Mettre à jour la progression
    migration.update_progress(
        percentage=progress.progress_percentage,
        step=progress.current_step,
        step_number=progress.current_step_number
    )

    if progress.transferred_gb is not None:
        migration.transferred_gb = progress.transferred_gb

    if progress.transfer_rate_mbps is not None:
        migration.transfer_rate_mbps = progress.transfer_rate_mbps

    db.commit()
    db.refresh(migration)

    return MigrationResponse.model_validate(migration)
