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
from app.models.virtual_machine import VirtualMachine
from app.schemas.migration import (
    MigrationCancel,
    MigrationCreate,
    MigrationUpdate,
    MigrationProgressUpdate,
    MigrationResponse,
    MigrationListResponse,
    MigrationStats
)

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
    # Construction de la requête
    query = db.query(Migration)

    # Multi-tenancy isolation
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)

    # Filtres
    if status_filter:
        query = query.filter(Migration.status == status_filter)

    if strategy:
        query = query.filter(Migration.strategy == strategy)

    if vm_id:
        query = query.filter(Migration.vm_id == vm_id)

    # Total count
    total = query.count()

    # Pagination
    migrations = query.order_by(Migration.created_at.desc()).offset(skip).limit(limit).all()

    # Convertir en schémas Pydantic
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
    vm_query = db.query(VirtualMachine).filter(VirtualMachine.id == migration_data.vm_id)
    if not current_user.is_superuser:
        vm_query = vm_query.filter(VirtualMachine.tenant_id == current_user.tenant_id)
    vm = vm_query.first()

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
    migration = Migration(
        **migration_data.model_dump(exclude_unset=True),
        tenant_id=current_user.tenant_id,
        target_namespace=f"shiftwise-{current_user.tenant_id}",
        status=MigrationStatus.PENDING
    )

    db.add(migration)
    db.commit()
    db.refresh(migration)

    return MigrationResponse.model_validate(migration)


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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    # Champs protégés — status par le worker Celery, target_namespace immuable après création
    _MIGRATION_PROTECTED_FIELDS = {"status", "target_namespace"}

    # Appliquer les modifications
    update_data = migration_update.model_dump(exclude_unset=True, exclude=_MIGRATION_PROTECTED_FIELDS)
    for field, value in update_data.items():
        setattr(migration, field, value)

    db.commit()
    db.refresh(migration)

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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    # Ne pas supprimer une migration en cours
    if migration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer une migration en cours"
        )

    db.delete(migration)
    db.commit()

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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

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
    query = db.query(Migration).filter(Migration.id == migration_id)
    if not current_user.is_superuser:
        query = query.filter(Migration.tenant_id == current_user.tenant_id)
    migration = query.first()

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


@router.get("/stats/summary", response_model=MigrationStats)
def get_migrations_stats(
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("migrations", "read"))] = None
):
    """
    Statistiques globales des migrations.

    **Permissions requises :** migrations:read
    """
    def _scoped_query():
        q = db.query(Migration)
        if not current_user.is_superuser:
            q = q.filter(Migration.tenant_id == current_user.tenant_id)
        return q

    total = _scoped_query().count()
    completed = _scoped_query().filter(Migration.status == MigrationStatus.COMPLETED).count()
    failed = _scoped_query().filter(Migration.status == MigrationStatus.FAILED).count()

    # Migrations en cours
    in_progress = _scoped_query().filter(Migration.status.in_([
        MigrationStatus.VALIDATING,
        MigrationStatus.PREPARING,
        MigrationStatus.TRANSFERRING,
        MigrationStatus.CONFIGURING,
        MigrationStatus.STARTING,
        MigrationStatus.VERIFYING
    ])).count()

    pending = _scoped_query().filter(Migration.status == MigrationStatus.PENDING).count()

    # Taux de succès
    success_rate = (completed / total * 100) if total > 0 else 0.0

    # Durée moyenne (migrations terminées)
    completed_migrations = _scoped_query().filter(
        Migration.status == MigrationStatus.COMPLETED
    ).all()

    avg_duration = None
    if completed_migrations:
        total_duration = sum(m.duration_seconds for m in completed_migrations)
        avg_duration = int(total_duration / len(completed_migrations))

    # Total données transférées — scopé par tenant
    total_transferred_query = db.query(func.sum(Migration.transferred_gb))
    if not current_user.is_superuser:
        total_transferred_query = total_transferred_query.filter(
            Migration.tenant_id == current_user.tenant_id
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