"""
CRUD pour MigrationEvent — journal d'audit append-only.

Pas de mise à jour ni de suppression : ces événements sont écrits par
``crud_migration.set_migration_status`` et lus en consultation seule. Le
endpoint ``GET /migrations/{id}/events`` ne supporte que la lecture
paginée par ``sequence_id``.

L'ordre canonique est ``sequence_id`` ascending par migration. Le
timestamp est conservé pour les requêtes de fenêtre temporelle mais ne
détermine PAS l'ordre des événements (rafale de heartbeats, dérive
d'horloge entre workers — Q2 production-readiness).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.migration import Migration, MigrationStatus
from app.models.migration_event import MigrationEvent, MigrationEventType

logger = logging.getLogger(__name__)

# SV-021 — préfixe du chaînage pour la toute première ligne d'une migration
# (genesis). Une chaîne d'audit débute donc à un état connu et constant.
_GENESIS_HASH = ""


def _canonical_chain_payload(
    *,
    migration_id: int,
    tenant_id: str,
    sequence_id: int,
    event_type_value: str,
    from_status: Optional[str],
    to_status: Optional[str],
    actor_id: Optional[int],
    actor_type: str,
    message: Optional[str],
    payload: Optional[dict],
) -> str:
    """Sérialise de façon déterministe les champs chaînés d'un événement.

    Exclut ``created_at`` (fixé par la DB après calcul) et l'``id`` auto :
    le chaînage couvre le CONTENU sémantique de l'audit, stable et connu
    avant flush. ``sort_keys`` garantit le déterminisme inter-process.
    """
    return json.dumps(
        {
            "migration_id": migration_id,
            "tenant_id": tenant_id,
            "sequence_id": sequence_id,
            "event_type": event_type_value,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "message": message,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _compute_row_hash(prev_hash: str, canonical: str) -> str:
    """``sha256(prev_hash || canonical_payload)`` en hexadécimal (64 chars)."""
    return hashlib.sha256(
        f"{prev_hash}{canonical}".encode("utf-8")
    ).hexdigest()


def _previous_row_hash(db: Session, migration_id: int) -> str:
    """Retourne le ``row_hash`` de la dernière ligne de la migration.

    ``_GENESIS_HASH`` si la migration n'a pas encore d'événement, ou si la
    dernière ligne est une ligne legacy non chaînée (``row_hash`` NULL) —
    dans ce dernier cas la nouvelle chaîne redémarre proprement.
    """
    last = (
        db.query(MigrationEvent.row_hash)
        .filter(MigrationEvent.migration_id == migration_id)
        .order_by(MigrationEvent.sequence_id.desc())
        .first()
    )
    if last is None or last[0] is None:
        return _GENESIS_HASH
    return last[0]

# Acteurs autorisés sur la colonne `actor_type` (modèle + schéma).
# Listés une fois pour ne pas dupliquer la canonicalisation entre le
# service Pydantic et la couche CRUD.
_ALLOWED_ACTOR_TYPES = ("worker", "user", "system")


def _next_sequence_id(db: Session, migration_id: int) -> int:
    """Allocate the next ``sequence_id`` for a migration.

    Locks the parent ``Migration`` row via ``SELECT ... FOR UPDATE`` so
    concurrent emitters cannot collide on ``(migration_id, sequence_id)``.
    Under PostgreSQL this is a real row lock; under SQLite (tests) the
    statement is a no-op and concurrency is precluded by the single
    writer thread.

    Avant le verrou on positionne ``lock_timeout=2s`` (Postgres only) —
    sans timeout, deux emitters concurrents peuvent rester bloqués
    indéfiniment sur la même ligne ; deux secondes nous ramènent un
    ``OperationalError`` classifiable en ``ERR_MIG_AUDIT_DEADLOCK`` au
    lieu de paralyser le worker.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
    db.query(Migration).filter(Migration.id == migration_id).with_for_update().first()
    current_max = (
        db.query(func.coalesce(func.max(MigrationEvent.sequence_id), 0))
        .filter(MigrationEvent.migration_id == migration_id)
        .scalar()
    )
    return int(current_max or 0) + 1


def list_events_for_migration(
    db: Session,
    migration_id: int,
    *,
    tenant_id: Optional[str] = None,
    since_sequence_id: int = 0,
    event_type: Optional[MigrationEventType] = None,
    limit: int = 200,
) -> List[MigrationEvent]:
    """Retourne les événements d'une migration, du plus ancien au plus récent.

    Ordre : ``sequence_id`` ascending (Q2). ``tenant_id`` filtre côté
    donnée — l'appelant API doit l'isolement multi-tenant.
    ``since_sequence_id`` autorise le polling delta : seuls les events
    avec ``sequence_id > since_sequence_id`` sont retournés.
    ``event_type`` filtre cross-migration (e.g.
    ``MigrationEventType.CLASSIFIED_ERROR`` pour les rapports d'incident).
    """
    query = db.query(MigrationEvent).filter(
        MigrationEvent.migration_id == migration_id,
    )
    if tenant_id is not None:
        query = query.filter(MigrationEvent.tenant_id == tenant_id)
    if since_sequence_id > 0:
        query = query.filter(MigrationEvent.sequence_id > since_sequence_id)
    if event_type is not None:
        query = query.filter(MigrationEvent.event_type == event_type)
    return (
        query
        .order_by(MigrationEvent.sequence_id.asc())
        .limit(limit)
        .all()
    )


def record_event(
    db: Session,
    *,
    migration_id: int,
    tenant_id: str,
    event_type: MigrationEventType,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_type: str = "worker",
    message: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> MigrationEvent:
    """Écrit un événement audit-log avec allocation atomique du ``sequence_id``.

    Par défaut ``commit=True`` flushe la ligne immédiatement ; passez
    ``commit=False`` pour grouper l'écriture dans la même transaction
    que l'auteur (ex. ``set_migration_status``). Le verrou ``FOR UPDATE``
    sur la migration parent garantit l'absence de collision sur
    ``(migration_id, sequence_id)`` même sous emit concurrent.

    ``actor_type`` est validé côté CRUD pour empêcher un appelant de
    glisser une chaîne non canonique (``"sys"``, ``"admin"``...) dans le
    journal d'audit. Le modèle déclare la colonne en ``String(16)``
    libre — donc cette validation est notre seul garde-fou.
    """
    if actor_type not in _ALLOWED_ACTOR_TYPES:
        raise ValueError(
            f"invalid actor_type {actor_type!r}; "
            f"must be one of {_ALLOWED_ACTOR_TYPES}"
        )
    sequence_id = _next_sequence_id(db, migration_id)
    # SV-021 — chaîne le hash de la ligne sur celui de la précédente. Le
    # verrou FOR UPDATE pris par _next_sequence_id sérialise déjà les
    # emitters concurrents, donc la lecture de _previous_row_hash est
    # cohérente avec l'allocation de sequence_id.
    prev_hash = _previous_row_hash(db, migration_id)
    canonical = _canonical_chain_payload(
        migration_id=migration_id,
        tenant_id=tenant_id,
        sequence_id=sequence_id,
        event_type_value=event_type.value,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        actor_type=actor_type,
        message=message,
        payload=payload,
    )
    event = MigrationEvent(
        migration_id=migration_id,
        tenant_id=tenant_id,
        sequence_id=sequence_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        actor_type=actor_type,
        message=message,
        payload=payload,
        row_hash=_compute_row_hash(prev_hash, canonical),
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def verify_event_chain(
    db: Session, migration_id: int
) -> Tuple[bool, Optional[int]]:
    """Vérifie le chaînage cryptographique des événements d'une migration.

    SV-021 — recalcule ``sha256(prev_hash || canonical)`` pour chaque ligne
    chaînée (``row_hash`` non NULL), dans l'ordre ``sequence_id`` ascendant,
    et compare au ``row_hash`` stocké. Toute suppression ou édition d'une
    ligne (même par un acteur contournant le trigger append-only, SV-001)
    casse le hash de la ligne suivante et est ici détectée.

    Les lignes legacy (``row_hash`` NULL, antérieures au chaînage) sont
    ignorées ; la vérification reprend à la première ligne chaînée, dont le
    prédécesseur effectif est le genesis.

    Returns:
        ``(True, None)`` si la chaîne est intacte ; ``(False, sequence_id)``
        en pointant la première ligne dont le hash ne concorde pas.
    """
    rows = (
        db.query(MigrationEvent)
        .filter(MigrationEvent.migration_id == migration_id)
        .order_by(MigrationEvent.sequence_id.asc())
        .all()
    )
    prev_hash = _GENESIS_HASH
    for row in rows:
        if row.row_hash is None:
            # Ligne legacy non chaînée — on (re)part du genesis derrière elle.
            prev_hash = _GENESIS_HASH
            continue
        canonical = _canonical_chain_payload(
            migration_id=row.migration_id,
            tenant_id=row.tenant_id,
            sequence_id=row.sequence_id,
            event_type_value=row.event_type.value,
            from_status=row.from_status,
            to_status=row.to_status,
            actor_id=row.actor_id,
            actor_type=row.actor_type,
            message=row.message,
            payload=row.payload,
        )
        expected = _compute_row_hash(prev_hash, canonical)
        if expected != row.row_hash:
            return False, row.sequence_id
        prev_hash = row.row_hash
    return True, None


def emit_heartbeat(
    db: Session,
    *,
    migration_id: int,
    tenant_id: str,
    current_status: MigrationStatus,
    message: Optional[str] = None,
    commit: bool = False,
) -> MigrationEvent:
    """Écrit un événement HEARTBEAT pour une étape longue (TRANSFERRING…).

    ``from_status`` est NULL (pas une transition), ``to_status`` répète
    le statut courant pour permettre au timeline UI d'afficher la durée
    écoulée dans la même étape. Le défaut ``commit=False`` reflète
    l'usage attendu : appel depuis la boucle du worker, qui commit en
    bloc à la fin de l'étape.
    """
    return record_event(
        db,
        migration_id=migration_id,
        tenant_id=tenant_id,
        event_type=MigrationEventType.HEARTBEAT,
        from_status=None,
        to_status=current_status.value,
        actor_type="worker",
        message=message,
        commit=commit,
    )
