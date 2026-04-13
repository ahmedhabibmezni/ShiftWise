"""
Schémas Pydantic pour Migration

Définit les schémas de validation et sérialisation pour l'API REST.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime

from app.models.migration import MigrationStatus as MigrationStatusEnum
from app.models.migration import MigrationStrategy as MigrationStrategyEnum


# Schéma de base
class MigrationBase(BaseModel):
    """Propriétés de base d'une migration"""
    strategy: MigrationStrategyEnum = Field(
        MigrationStrategyEnum.AUTO,
        description="Stratégie de migration"
    )
    # target_namespace RETIRÉ — auto-calculé depuis le tenant (shiftwise-{tenant_id})
    target_storage_class: str = Field(
        "nfs-client",
        min_length=1,
        max_length=255,
        description="StorageClass OpenShift"
    )


# Schéma pour la création
class MigrationCreate(MigrationBase):
    """Schéma pour créer une migration"""
    vm_id: int = Field(..., description="ID de la VM à migrer")
    scheduled_at: Optional[datetime] = Field(None, description="Date de planification")
    migration_config: Optional[dict] = Field(None, description="Configuration spécifique")
    notes: Optional[str] = Field(None, description="Notes")
    tags: Optional[dict] = Field(None, description="Tags personnalisés")


# Schéma pour la mise à jour
class MigrationUpdate(BaseModel):
    """Schéma pour mettre à jour une migration.

    status est géré exclusivement par le worker Celery — non accepté ici.
    """
    strategy: Optional[MigrationStrategyEnum] = None
    scheduled_at: Optional[datetime] = None
    # target_namespace RETIRÉ — immuable après création
    target_storage_class: Optional[str] = Field(None, min_length=1, max_length=255)
    migration_config: Optional[dict] = None
    notes: Optional[str] = None
    tags: Optional[dict] = None


# Schéma pour annuler une migration
class MigrationCancel(BaseModel):
    """Schéma pour annuler une migration"""
    reason: Optional[str] = Field(None, max_length=500, description="Raison de l'annulation")


# Schéma pour mettre à jour la progression
class MigrationProgressUpdate(BaseModel):
    """Schéma pour mettre à jour la progression"""
    progress_percentage: float = Field(..., ge=0.0, le=100.0, description="Pourcentage de progression")
    current_step: str = Field(..., min_length=1, max_length=255, description="Étape actuelle")
    current_step_number: Optional[int] = Field(None, ge=0, description="Numéro de l'étape")
    transferred_gb: Optional[float] = Field(None, ge=0.0, description="Données transférées en GB")
    transfer_rate_mbps: Optional[float] = Field(None, ge=0.0, description="Vitesse de transfert en Mbps")


# Schéma pour la réponse
class MigrationResponse(MigrationBase):
    """Schéma de réponse complète"""
    id: int
    vm_id: int
    status: MigrationStatusEnum
    target_namespace: str  # lecture seule — auto-calculé à la création
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress_percentage: float
    current_step: Optional[str] = None
    current_step_number: int
    total_steps: int
    success: Optional[bool] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    migration_config: Optional[dict] = None
    source_size_gb: Optional[float] = None
    transferred_gb: float
    transfer_rate_mbps: Optional[float] = None
    target_vm_name: Optional[str] = None
    target_node: Optional[str] = None
    requires_conversion: bool
    conversion_format: Optional[str] = None
    conversion_started_at: Optional[datetime] = None
    conversion_completed_at: Optional[datetime] = None
    pre_migration_checks: Optional[dict] = None
    post_migration_checks: Optional[dict] = None
    can_rollback: bool
    tags: Optional[dict] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Propriétés calculées
    is_active: bool
    is_completed: bool
    duration_seconds: int
    estimated_time_remaining_seconds: int

    model_config = ConfigDict(from_attributes=True)


# Schéma pour liste paginée
class MigrationListResponse(BaseModel):
    """Réponse pour liste de migrations"""
    total: int = Field(..., description="Nombre total de migrations")
    items: list[MigrationResponse] = Field(..., description="Liste des migrations")
    page: int = Field(..., ge=1, description="Page actuelle")
    page_size: int = Field(..., ge=1, le=100, description="Taille de la page")


# Schéma pour démarrer une migration
class MigrationStart(BaseModel):
    """Schéma pour démarrer une migration"""
    migration_id: int = Field(..., description="ID de la migration à démarrer")


# Schéma pour annuler une migration
class MigrationCancel(BaseModel):
    """Schéma pour annuler une migration"""
    migration_id: int = Field(..., description="ID de la migration à annuler")
    reason: Optional[str] = Field(None, max_length=500, description="Raison de l'annulation")


# Schéma pour rollback
class MigrationRollback(BaseModel):
    """Schéma pour rollback d'une migration"""
    migration_id: int = Field(..., description="ID de la migration à rollback")
    reason: Optional[str] = Field(None, max_length=500, description="Raison du rollback")


# Schéma de statistiques
class MigrationStats(BaseModel):
    """Statistiques globales des migrations"""
    total_migrations: int
    completed: int
    failed: int
    in_progress: int
    pending: int
    success_rate: float = Field(..., ge=0.0, le=100.0, description="Taux de succès en %")
    average_duration_seconds: Optional[int] = None
    total_data_transferred_gb: float