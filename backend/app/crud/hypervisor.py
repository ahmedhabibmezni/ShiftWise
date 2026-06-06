"""
ShiftWise Hypervisor CRUD Operations

Opérations CRUD (Create, Read, Update, Delete) pour les hyperviseurs.

Toutes les fonctions prennent une session SQLAlchemy en paramètre
et retournent des objets du modèle Hypervisor.
Filtrage multi-tenancy via tenant_id optionnel.
"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.services.credentials import get_vault


# Audit D6 — champs jamais modifiables via update_hypervisor, même si un
# appelant ou une évolution du schéma les injecte dans le dict de mise à
# jour. `status` est piloté exclusivement par le Discovery Service ;
# `tenant_id` est fixé à la création et garantit l'isolation multi-tenant.
_HYPERVISOR_PROTECTED_FIELDS = frozenset({
    "id", "tenant_id", "status", "created_at", "updated_at",
    "total_vms_discovered", "total_vms_migrated",
    "last_sync_at", "last_successful_connection", "last_error",
})


def get_hypervisor(
        db: Session,
        hypervisor_id: int,
        tenant_id: Optional[str] = None
) -> Optional[Hypervisor]:
    """
    Recupere un hypervisor par son ID.

    Args:
        db: Session de base de donnees
        hypervisor_id: ID de l'hypervisor
        tenant_id: Si fourni, filtre par tenant (multi-tenancy)

    Returns:
        Hypervisor si trouve, None sinon
    """
    query = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id)
    if tenant_id is not None:
        query = query.filter(Hypervisor.tenant_id == tenant_id)
    return query.first()


def get_hypervisor_by_name(
        db: Session,
        name: str,
        tenant_id: Optional[str] = None,
) -> Optional[Hypervisor]:
    """
    Recupere un hypervisor par son nom.

    Args:
        db: Session de base de donnees
        name: Nom de l'hypervisor
        tenant_id: Si fourni, filtre par tenant (multi-tenancy) — Audit B14.
            Le nom n'etant unique que par tenant (Audit B15), ce filtre est
            necessaire pour cibler le bon enregistrement et eviter une fuite
            d'existence entre tenants.

    Returns:
        Hypervisor si trouve, None sinon
    """
    query = db.query(Hypervisor).filter(Hypervisor.name == name)
    if tenant_id is not None:
        query = query.filter(Hypervisor.tenant_id == tenant_id)
    return query.first()


def get_hypervisors(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        hypervisor_type: Optional[HypervisorType] = None,
        status: Optional[HypervisorStatus] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
) -> List[Hypervisor]:
    """
    Recupere une liste d'hypervisors avec filtres et pagination.

    Args:
        db: Session de base de donnees
        skip: Nombre d'elements a ignorer (pagination)
        limit: Nombre maximum d'elements a retourner
        tenant_id: Filtrer par tenant (multi-tenancy)
        hypervisor_type: Filtrer par type d'hyperviseur
        status: Filtrer par statut
        is_active: Filtrer par etat actif/inactif
        search: Rechercher par nom ou host (ilike)

    Returns:
        Liste d'hypervisors
    """
    query = db.query(Hypervisor)

    if tenant_id is not None:
        query = query.filter(Hypervisor.tenant_id == tenant_id)

    if hypervisor_type is not None:
        query = query.filter(Hypervisor.type == hypervisor_type)

    if status is not None:
        query = query.filter(Hypervisor.status == status)

    if is_active is not None:
        query = query.filter(Hypervisor.is_active == is_active)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Hypervisor.name.ilike(search_filter)) |
            (Hypervisor.host.ilike(search_filter))
        )

    return query.offset(skip).limit(limit).all()


def get_hypervisors_count(
        db: Session,
        tenant_id: Optional[str] = None,
        hypervisor_type: Optional[HypervisorType] = None,
        status: Optional[HypervisorStatus] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
) -> int:
    """
    Compte le nombre total d'hypervisors avec les memes filtres.

    Args:
        db: Session de base de donnees
        tenant_id: Filtrer par tenant
        hypervisor_type: Filtrer par type
        status: Filtrer par statut
        is_active: Filtrer par etat actif/inactif
        search: Rechercher par nom ou host

    Returns:
        Nombre d'hypervisors correspondants
    """
    query = db.query(Hypervisor)

    if tenant_id is not None:
        query = query.filter(Hypervisor.tenant_id == tenant_id)

    if hypervisor_type is not None:
        query = query.filter(Hypervisor.type == hypervisor_type)

    if status is not None:
        query = query.filter(Hypervisor.status == status)

    if is_active is not None:
        query = query.filter(Hypervisor.is_active == is_active)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Hypervisor.name.ilike(search_filter)) |
            (Hypervisor.host.ilike(search_filter))
        )

    return query.count()


def create_hypervisor(db: Session, data: dict, tenant_id: str) -> Hypervisor:
    """
    Cree un nouvel hypervisor.

    Args:
        db: Session de base de donnees
        data: Champs de l'hypervisor (depuis schema.model_dump)
        tenant_id: Tenant proprietaire

    Returns:
        Hypervisor cree

    Raises:
        ValueError: Si un hypervisor avec ce nom existe deja
    """
    # Audit B15 — l'unicite du nom est desormais par tenant : la verification
    # prealable doit etre scopee au meme tenant.
    existing = get_hypervisor_by_name(db, data.get("name", ""), tenant_id=tenant_id)
    if existing:
        raise ValueError(f"Un hypervisor avec le nom '{data['name']}' existe déjà")

    # US4 — chiffrer le mot de passe avant insertion. Le plaintext n'est
    # JAMAIS persisté ; seul `password_ciphertext` (Fernet) l'est. La colonne
    # legacy `password` a été dropée par la migration `c9e1d4f3b6a2`.
    raw_password = data.pop("password", None)

    hypervisor = Hypervisor(
        **data,
        tenant_id=tenant_id,
        status=HypervisorStatus.UNKNOWN
    )
    if raw_password:
        vault = get_vault()
        hypervisor.password_ciphertext = vault.encrypt(raw_password)
        hypervisor.credential_key_version = vault.key_version
        hypervisor.credentials_updated_at = vault.now_utc()

    db.add(hypervisor)
    db.commit()
    db.refresh(hypervisor)

    return hypervisor


def update_hypervisor(
        db: Session,
        hypervisor_id: int,
        update_data: dict,
        tenant_id: Optional[str] = None
) -> Optional[Hypervisor]:
    """
    Met a jour un hypervisor existant.

    Args:
        db: Session de base de donnees
        hypervisor_id: ID de l'hypervisor a mettre a jour
        update_data: Champs a mettre a jour (exclude_unset=True)
        tenant_id: Si fourni, filtre par tenant

    Returns:
        Hypervisor mis a jour si trouve, None sinon
    """
    hypervisor = get_hypervisor(db, hypervisor_id, tenant_id=tenant_id)
    if not hypervisor:
        return None

    # Audit C15 — un renommage vers un nom déjà pris par le même tenant doit
    # échouer proprement (ValueError → 409 côté routeur), pas en IntegrityError
    # opaque → 500. Pré-vérification scopée au tenant propriétaire de la ligne.
    new_name = update_data.get("name")
    if new_name and new_name != hypervisor.name:
        clash = get_hypervisor_by_name(db, new_name, tenant_id=hypervisor.tenant_id)
        if clash and clash.id != hypervisor.id:
            raise ValueError(f"Un hypervisor avec le nom '{new_name}' existe déjà")

    # US4 — un update sur `password` chiffre la nouvelle valeur dans
    # `password_ciphertext`. La colonne legacy `password` n'existe plus
    # (dropée par la migration `c9e1d4f3b6a2`).
    raw_password = update_data.pop("password", None)
    if raw_password:
        vault = get_vault()
        hypervisor.password_ciphertext = vault.encrypt(raw_password)
        hypervisor.credential_key_version = vault.key_version
        hypervisor.credentials_updated_at = vault.now_utc()

    for field, value in update_data.items():
        if field in _HYPERVISOR_PROTECTED_FIELDS:
            continue  # Audit D6 — champ protégé, ignoré silencieusement
        setattr(hypervisor, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        # Filet anti-course (TOCTOU) : deux renommages concurrents passent tous
        # deux la pré-vérification puis heurtent la contrainte composite
        # (tenant_id, name). On le rattrape en ValueError → 409.
        db.rollback()
        raise ValueError(
            f"Un hypervisor avec le nom '{new_name}' existe déjà"
        ) from exc
    db.refresh(hypervisor)

    return hypervisor


def delete_hypervisor(
        db: Session,
        hypervisor_id: int,
        tenant_id: Optional[str] = None
) -> bool:
    """
    Supprime un hypervisor.

    Args:
        db: Session de base de donnees
        hypervisor_id: ID de l'hypervisor a supprimer
        tenant_id: Si fourni, filtre par tenant

    Returns:
        True si supprime, False si non trouve

    Note:
        Les VMs associees auront leur source_hypervisor_id mis a NULL (SET NULL).
    """
    hypervisor = get_hypervisor(db, hypervisor_id, tenant_id=tenant_id)
    if not hypervisor:
        return False

    db.delete(hypervisor)
    db.commit()

    return True
