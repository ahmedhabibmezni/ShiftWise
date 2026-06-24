"""
Modèle MigrationEvent — journal d'audit append-only.

Une ligne est écrite à chaque événement journalisable de la machine à états
d'une migration. Couvre quatre catégories d'événements (Q1, spec
production-readiness) :

- ``STATE_TRANSITION`` : transition entre deux ``MigrationStatus``.
- ``STAGE_EVENT``      : sous-étape du pipeline (job converter / adapter /
                         migrator démarré / terminé).
- ``CLASSIFIED_ERROR`` : erreur classifiée (ERR_MIG_K8S_TIMEOUT,
                         ERR_MIG_NAMESPACE_FORBIDDEN, etc.).
- ``HEARTBEAT``        : signe de vie périodique (~30 s) émis pendant les
                         étapes longues, principalement TRANSFERRING.

L'ordre canonique de lecture est ``(migration_id, sequence_id)`` ascending
— jamais le timestamp seul (Q2). Le timestamp ``created_at`` reste
disponible pour les requêtes de fenêtre temporelle mais NE détermine PAS
l'ordre des événements (rafale de heartbeats sub-milliseconde, dérive
d'horloge entre workers).

Le FK vers ``migrations.id`` utilise ``NO ACTION`` (Q3.A) : la durée de
vie du journal est indépendante de la migration parent. Supprimer une
migration alors qu'il existe des événements rattachés lèvera une
``ForeignKeyViolation`` — c'est exactement la garantie de rétention.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import backref, relationship

from app.models.base import BaseModel


class MigrationEventType(str, enum.Enum):
    """Type d'événement journalisé.

    Les valeurs sont en minuscule pour rester stables face à un renommage
    futur (les lignes audit ne doivent jamais perdre leur typage). Le
    label SQL côté PostgreSQL est aligné sur ``.value`` via le ``SQLEnum``
    ci-dessous (``values_callable``).
    """

    STATE_TRANSITION = "state_transition"
    STAGE_EVENT = "stage_event"
    CLASSIFIED_ERROR = "classified_error"
    HEARTBEAT = "heartbeat"


# Acteurs reconnus. ``worker`` couvre les jobs Celery / K8s ; ``user``
# couvre les actions opérateur (cancel, retry) ; ``system`` couvre les
# transitions internes (e.g. timeout watchdog).
_ACTOR_TYPES = ("worker", "user", "system")


class MigrationEvent(BaseModel):
    """Événement append-only d'une migration.

    Le timestamp d'enregistrement est ``created_at`` (hérité de
    :class:`BaseModel`). ``from_status``/``to_status`` portent la valeur
    ``MigrationStatus.value`` (minuscule) plutôt que le nom du membre afin
    d'être stables face à un renommage futur du libellé enum côté
    PostgreSQL — l'audit-log doit pouvoir conserver des statuts
    historiques.
    """

    __tablename__ = "migration_events"

    # Multi-tenancy — dénormalisé depuis migrations.tenant_id pour les
    # requêtes audit par tenant sans JOIN.
    tenant_id = Column(String(100), nullable=False, index=True)

    migration_id = Column(
        Integer,
        # Q3.A — rétention indépendante : audit survit à la suppression
        # de la migration parent. Une tentative de suppression lève FK
        # violation, ce qui force l'opérateur à utiliser la procédure
        # documentée d'archivage (docs/operations/audit-trail-query.md).
        ForeignKey("migrations.id", ondelete="NO ACTION"),
        nullable=False,
    )

    # Q2 — séquence monotone par migration ; primitif d'ordre canonique.
    # Allocée atomiquement dans crud_migration_event.record_event via
    # SELECT ... FOR UPDATE sur la dernière sequence_id de la migration.
    sequence_id = Column(Integer, nullable=False)

    event_type = Column(
        SQLEnum(
            MigrationEventType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            name="migrationeventtype",
        ),
        nullable=False,
        default=MigrationEventType.STATE_TRANSITION,
        server_default=MigrationEventType.STATE_TRANSITION.value,
    )

    # Renseignés pour STATE_TRANSITION / CLASSIFIED_ERROR. NULL pour
    # HEARTBEAT et certains STAGE_EVENT.
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)

    # Acteur — utilisateur (cancel/retry) ou worker (transition pipeline).
    actor_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type = Column(
        String(16),
        nullable=False,
        default="worker",
        server_default="worker",
    )

    # Message libre — texte d'erreur, raison d'annulation, note utilisateur.
    message = Column(Text, nullable=True)

    # Charge utile JSON pour les métadonnées structurées (error_code, etc.).
    payload = Column(JSON, nullable=True)

    # SV-021 — chaînage cryptographique de détection de falsification.
    # ``row_hash = sha256(prev_row_hash || canonical_payload)`` par
    # ``migration_id``. Toute suppression ou édition d'une ligne (y compris
    # par un superuser DB contournant le trigger append-only, cf. SV-001)
    # casse le chaînage de la ligne suivante et devient détectable à la
    # vérification (``crud.migration_event.verify_event_chain``). Nullable :
    # les lignes antérieures à l'introduction du chaînage portent NULL et
    # sont traitées comme « legacy non chaînées » par le vérificateur.
    row_hash = Column(String(64), nullable=True)

    __table_args__ = (
        # Q2 — uniqueness (migration_id, sequence_id). Allocation atomique
        # via le verrou FOR UPDATE de crud_migration_event.
        UniqueConstraint(
            "migration_id", "sequence_id", name="uq_migration_events_seq",
        ),
        # Defense-in-depth pour ``actor_type`` : la colonne est un
        # ``String(16)`` libre et ``record_event`` valide la valeur côté
        # CRUD (``_ALLOWED_ACTOR_TYPES``). Une CHECK contrainte côté DB
        # bloque tout INSERT brut hors ORM (script ad hoc, future
        # routine d'archivage) qui tenterait de glisser une chaîne non
        # canonique dans le journal d'audit.
        CheckConstraint(
            "actor_type IN ('worker', 'user', 'system')",
            name="ck_migration_events_actor_type",
        ),
        # Index principal — chemin de lecture du timeline UI et du
        # endpoint d'audit.
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
        # Filtre cross-migration ("show me all classified_error events
        # across the cluster in the last 24 h").
        Index(
            "ix_migration_events_event_type",
            "event_type",
        ),
    )

    # ``passive_deletes=True`` : ne PAS émettre d'``UPDATE migration_events
    # SET migration_id=NULL`` quand la migration parent est supprimée. La
    # colonne est ``NOT NULL`` et la table est append-only (trigger DB) — la
    # tentative de nullify échouait en 500. On laisse la contrainte FK
    # ``ON DELETE NO ACTION`` parler : si des événements existent, le DELETE
    # parent lève une ``IntegrityError`` propre (rétention de l'audit), gérée
    # en 409 par la couche CRUD/API.
    migration = relationship(
        "Migration",
        backref=backref("events", passive_deletes=True),
    )
    actor = relationship("User", foreign_keys=[actor_id])

    def __repr__(self) -> str:
        return (
            f"<MigrationEvent(id={self.id}, migration_id={self.migration_id}, "
            f"seq={self.sequence_id}, type={self.event_type.value}, "
            f"{self.from_status}->{self.to_status})>"
        )
