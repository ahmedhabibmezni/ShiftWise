"""
Modèle Migration

Représente une opération de migration d'une VM depuis un hyperviseur source
vers OpenShift Virtualization.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum, ForeignKey, JSON, Float, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.models.base import BaseModel


class MigrationStatus(str, enum.Enum):
    """Statut d'une migration"""
    PENDING = "pending"                   # En attente de démarrage
    VALIDATING = "validating"             # Validation pré-migration
    PREPARING = "preparing"               # Préparation (conversion disques, etc.)
    TRANSFERRING = "transferring"         # Transfert des données
    CONFIGURING = "configuring"           # Configuration dans OpenShift
    STARTING = "starting"                 # Démarrage de la VM
    VERIFYING = "verifying"               # Vérification post-migration
    COMPLETED = "completed"               # Migration réussie
    FAILED = "failed"                     # Échec de migration
    CANCELLED = "cancelled"               # Annulée par l'utilisateur
    ROLLBACK = "rollback"                 # Rollback en cours
    ROLLED_BACK = "rolled_back"           # Rollback terminé


class MigrationStrategy(str, enum.Enum):
    """Stratégie de migration"""
    DIRECT = "direct"                     # Migration directe sans conversion
    CONVERSION = "conversion"             # Avec conversion de format (VMDK→QCOW2)
    HYBRID = "hybrid"                     # Migration hybride (mix direct + conversion)
    COLD = "cold"                         # Migration à froid (VM arrêtée)
    WARM = "warm"                         # Migration à chaud (avec réplication)
    AUTO = "auto"                         # Sélection automatique par l'IA


class Migration(BaseModel):
    """
    Modèle représentant une migration de VM.

    Stocke l'historique complet d'une opération de migration depuis
    la source jusqu'à OpenShift Virtualization.
    """

    __tablename__ = "migrations"

    # VM concernée
    vm_id = Column(
        Integer,
        ForeignKey("virtual_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Statut et progression
    status = Column(SQLEnum(MigrationStatus), nullable=False, default=MigrationStatus.PENDING, index=True)
    strategy = Column(SQLEnum(MigrationStrategy), nullable=False, default=MigrationStrategy.AUTO)

    # Timing
    scheduled_at = Column(DateTime, nullable=True)  # Migration planifiée
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Progression
    progress_percentage = Column(Float, default=0.0)  # 0-100
    current_step = Column(String(255), nullable=True)  # Étape actuelle
    total_steps = Column(Integer, default=7)  # Nombre total d'étapes
    current_step_number = Column(Integer, default=0)  # Numéro étape actuelle

    # Résultat
    success = Column(Boolean, nullable=True)  # True=succès, False=échec, None=en cours
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)

    # Configuration de migration
    migration_config = Column(JSON, nullable=True)  # Paramètres spécifiques

    # Données de transfert
    source_size_gb = Column(Float, nullable=True)  # Taille source
    transferred_gb = Column(Float, default=0.0)    # Données transférées
    transfer_rate_mbps = Column(Float, nullable=True)  # Vitesse de transfert

    # OpenShift destination
    target_namespace = Column(String(255), nullable=False, default="default")
    target_vm_name = Column(String(255), nullable=True)
    target_storage_class = Column(String(255), nullable=True, default="nfs-client")
    target_node = Column(String(255), nullable=True)  # Node OpenShift cible

    # Conversion (si nécessaire)
    requires_conversion = Column(Boolean, default=False)
    conversion_format = Column(String(50), nullable=True)  # Ex: "vmdk_to_qcow2"
    conversion_started_at = Column(DateTime, nullable=True)
    conversion_completed_at = Column(DateTime, nullable=True)

    # Validation
    pre_migration_checks = Column(JSON, nullable=True)   # Résultats checks pré-migration
    post_migration_checks = Column(JSON, nullable=True)  # Résultats checks post-migration

    # Logs
    log_file_path = Column(String(512), nullable=True)  # Chemin vers fichier de logs

    # Rollback
    can_rollback = Column(Boolean, default=True)
    rollback_snapshot_id = Column(String(255), nullable=True)  # ID snapshot pour rollback

    # Métadonnées
    tags = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)  # Notes de l'utilisateur

    # Relations
    virtual_machine = relationship(
        "VirtualMachine",
        back_populates="migrations",
        foreign_keys=[vm_id]
    )

    def __repr__(self):
        return (
            f"<Migration(id={self.id}, vm_id={self.vm_id}, "
            f"status={self.status.value}, progress={self.progress_percentage}%)>"
        )

    @property
    def is_active(self) -> bool:
        """Vérifie si la migration est en cours"""
        return self.status in [
            MigrationStatus.PENDING,
            MigrationStatus.VALIDATING,
            MigrationStatus.PREPARING,
            MigrationStatus.TRANSFERRING,
            MigrationStatus.CONFIGURING,
            MigrationStatus.STARTING,
            MigrationStatus.VERIFYING
        ]

    @property
    def is_completed(self) -> bool:
        """Vérifie si la migration est terminée (succès ou échec)"""
        return self.status in [
            MigrationStatus.COMPLETED,
            MigrationStatus.FAILED,
            MigrationStatus.CANCELLED,
            MigrationStatus.ROLLED_BACK
        ]

    @property
    def duration_seconds(self) -> int:
        """Calcule la durée de la migration en secondes"""
        if not self.started_at:
            return 0

        # Assurer que started_at est timezone-aware
        started = self.started_at
        if started.tzinfo is None:
            from datetime import timezone as tz
            started = started.replace(tzinfo=tz.utc)

        # Assurer que end_time est timezone-aware
        if self.completed_at:
            end_time = self.completed_at
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=tz.utc)
        else:
            end_time = datetime.now(timezone.utc)

        delta = end_time - started
        return int(delta.total_seconds())

    @property
    def estimated_time_remaining_seconds(self) -> int:
        """Estime le temps restant en secondes"""
        if not self.is_active or self.progress_percentage == 0:
            return 0

        elapsed = self.duration_seconds
        estimated_total = (elapsed / self.progress_percentage) * 100
        return int(estimated_total - elapsed)

    def update_progress(self, percentage: float, step: str, step_number: int = None):
        """Met à jour la progression de la migration"""
        self.progress_percentage = min(100.0, max(0.0, percentage))
        self.current_step = step

        if step_number is not None:
            self.current_step_number = step_number

        self.updated_at = datetime.now(timezone.utc)

    def mark_started(self):
        """Marque la migration comme démarrée"""
        self.started_at = datetime.now(timezone.utc)
        self.status = MigrationStatus.VALIDATING
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, success: bool, error_message: str = None):
        """Marque la migration comme terminée"""
        self.completed_at = datetime.now(timezone.utc)
        self.progress_percentage = 100.0
        self.success = success

        if success:
            self.status = MigrationStatus.COMPLETED
            self.error_message = None
        else:
            self.status = MigrationStatus.FAILED
            self.error_message = error_message

        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Conversion en dictionnaire pour API"""
        return {
            "id": str(self.id),
            "vm_id": str(self.vm_id),
            "status": self.status.value,
            "strategy": self.strategy.value,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress_percentage": self.progress_percentage,
            "current_step": self.current_step,
            "current_step_number": self.current_step_number,
            "total_steps": self.total_steps,
            "success": self.success,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "migration_config": self.migration_config,
            "source_size_gb": self.source_size_gb,
            "transferred_gb": self.transferred_gb,
            "transfer_rate_mbps": self.transfer_rate_mbps,
            "target_namespace": self.target_namespace,
            "target_vm_name": self.target_vm_name,
            "target_storage_class": self.target_storage_class,
            "target_node": self.target_node,
            "requires_conversion": self.requires_conversion,
            "conversion_format": self.conversion_format,
            "pre_migration_checks": self.pre_migration_checks,
            "post_migration_checks": self.post_migration_checks,
            "can_rollback": self.can_rollback,
            "tags": self.tags,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "is_completed": self.is_completed,
            "duration_seconds": self.duration_seconds,
            "estimated_time_remaining_seconds": self.estimated_time_remaining_seconds
        }