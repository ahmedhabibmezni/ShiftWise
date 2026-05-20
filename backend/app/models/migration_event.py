"""
Modèle MigrationEvent — journal d'audit append-only.

Une ligne est écrite à chaque transition de statut par
``crud_migration.set_migration_status`` afin qu'un replay complet de la
machine à états reste possible même après un redémarrage du worker Celery
ou un rejeu de tâche. Les mises à jour de progression haute fréquence ne
sont PAS journalisées ici — seules les transitions et les erreurs.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    Column,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MigrationEventType(str, enum.Enum):
    """Type d'événement journalisé."""

    STATUS_CHANGE = "status_change"
    ERROR = "error"
    NOTE = "note"


class MigrationEvent(BaseModel):
    """
    Événement append-only d'une migration.

    Le timestamp d'enregistrement est ``created_at`` (hérité de
    :class:`BaseModel`). ``from_status``/``to_status`` portent la valeur
    ``MigrationStatus`` (minuscule, ``.value``) plutôt que le nom du membre
    afin d'être stables face à un renommage futur du libellé enum côté
    PostgreSQL — l'audit-log doit pouvoir conserver des statuts historiques.
    """

    __tablename__ = "migration_events"

    # Multi-tenancy — dénormalisé depuis migrations.tenant_id pour les
    # requêtes audit par tenant sans JOIN.
    tenant_id = Column(String(100), nullable=False, index=True)

    migration_id = Column(
        Integer,
        ForeignKey("migrations.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type = Column(
        SQLEnum(MigrationEventType),
        nullable=False,
        default=MigrationEventType.STATUS_CHANGE,
        server_default="STATUS_CHANGE",
    )

    # Renseignés pour STATUS_CHANGE / ERROR. NULL pour NOTE.
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)

    # Message libre — texte d'erreur, raison d'annulation, note utilisateur.
    message = Column(Text, nullable=True)

    # Charge utile JSON pour les métadonnées structurées (error_code, etc.).
    payload = Column(JSON, nullable=True)

    __table_args__ = (
        Index(
            "ix_migration_events_migration_created",
            "migration_id",
            "created_at",
        ),
        Index(
            "ix_migration_events_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    migration = relationship("Migration", backref="events")

    def __repr__(self) -> str:
        return (
            f"<MigrationEvent(id={self.id}, migration_id={self.migration_id}, "
            f"type={self.event_type.value}, "
            f"{self.from_status}->{self.to_status})>"
        )
