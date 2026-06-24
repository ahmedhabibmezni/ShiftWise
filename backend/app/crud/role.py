"""
ShiftWise Role CRUD Operations

Opérations CRUD (Create, Read, Update, Delete) pour les rôles.

Toutes les fonctions prennent une session SQLAlchemy en paramètre
et retournent des objets du modèle Role.
"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.role import Role, ROLE_PERMISSIONS
from app.schemas.role import RoleCreate, RoleUpdate


def get_role(db: Session, role_id: int) -> Optional[Role]:
    """
    Récupère un rôle par son ID.

    Args:
        db: Session de base de données
        role_id: ID du rôle

    Returns:
        Role si trouvé, None sinon

    Example:
        >>> role = get_role(db, 1)
        >>> print(role.name)
        'admin'
    """
    return db.query(Role).filter(Role.id == role_id).first()


def get_role_by_name(db: Session, name: str) -> Optional[Role]:
    """
    Récupère un rôle par son nom.

    Args:
        db: Session de base de données
        name: Nom du rôle

    Returns:
        Role si trouvé, None sinon

    Example:
        >>> role = get_role_by_name(db, "admin")
    """
    return db.query(Role).filter(Role.name == name.lower()).first()


def get_roles(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
) -> List[Role]:
    """
    Récupère une liste de rôles avec filtres et pagination.

    Args:
        db: Session de base de données
        skip: Nombre d'éléments à sauter (pagination)
        limit: Nombre maximum d'éléments à retourner
        is_active: Filtrer par statut actif/inactif (optionnel)
        search: Rechercher dans le nom ou description (optionnel)

    Returns:
        Liste de rôles

    Example:
        >>> roles = get_roles(db, skip=0, limit=10, is_active=True)
        >>> roles = get_roles(db, search="admin")
    """
    query = db.query(Role)

    # Filtre par statut actif
    if is_active is not None:
        query = query.filter(Role.is_active == is_active)

    # Recherche dans nom et description
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Role.name.ilike(search_term),
                Role.description.ilike(search_term)
            )
        )

    return query.offset(skip).limit(limit).all()


def get_roles_count(
        db: Session,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
) -> int:
    """
    Compte le nombre total de rôles avec les mêmes filtres.

    Args:
        db: Session de base de données
        is_active: Filtrer par statut actif/inactif
        search: Rechercher dans nom ou description

    Returns:
        Nombre de rôles correspondants
    """
    query = db.query(Role)

    if is_active is not None:
        query = query.filter(Role.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Role.name.ilike(search_term),
                Role.description.ilike(search_term)
            )
        )

    return query.count()


def create_role(db: Session, role: RoleCreate) -> Role:
    """
    Crée un nouveau rôle.

    Args:
        db: Session de base de données
        role: Données du rôle à créer (RoleCreate schema)

    Returns:
        Role créé

    Raises:
        ValueError: Si un rôle avec ce nom existe déjà

    Example:
        >>> role_data = RoleCreate(
        ...     name="project_manager",
        ...     permissions={"vms": ["read", "create"]}
        ... )
        >>> new_role = create_role(db, role_data)
    """
    # Vérifier si le rôle existe déjà
    existing_role = get_role_by_name(db, role.name)
    if existing_role:
        raise ValueError(f"Un rôle avec le nom '{role.name}' existe déjà")

    # Créer le nouveau rôle
    db_role = Role(
        name=role.name.lower(),
        description=role.description,
        permissions=role.permissions,
        is_active=role.is_active,
        is_system_role=False  # Les rôles créés manuellement ne sont pas système
    )

    db.add(db_role)
    db.commit()
    db.refresh(db_role)

    return db_role


def update_role(
        db: Session,
        role_id: int,
        role_update: RoleUpdate
) -> Optional[Role]:
    """
    Met à jour un rôle existant.

    Args:
        db: Session de base de données
        role_id: ID du rôle à mettre à jour
        role_update: Données à mettre à jour (RoleUpdate schema)

    Returns:
        Role mis à jour si trouvé, None sinon

    Raises:
        ValueError: Si tentative de modification d'un rôle système
        ValueError: Si le nouveau nom existe déjà

    Example:
        >>> update_data = RoleUpdate(description="Nouveau descriptif")
        >>> updated_role = update_role(db, 1, update_data)
    """
    db_role = get_role(db, role_id)

    if not db_role:
        return None

    # Empêcher la modification des rôles système
    if db_role.is_system_role:
        raise ValueError("Les rôles système ne peuvent pas être modifiés")

    # Mettre à jour uniquement les champs fournis
    update_data = role_update.model_dump(exclude_unset=True)

    # Vérifier le nom si changé
    if "name" in update_data:
        new_name = update_data["name"].lower()
        if new_name != db_role.name:
            existing = get_role_by_name(db, new_name)
            if existing:
                raise ValueError(f"Un rôle avec le nom '{new_name}' existe déjà")

    # Appliquer les mises à jour
    for field, value in update_data.items():
        setattr(db_role, field, value)

    db.commit()
    db.refresh(db_role)

    return db_role


def delete_role(db: Session, role_id: int) -> bool:
    """
    Supprime un rôle.

    Args:
        db: Session de base de données
        role_id: ID du rôle à supprimer

    Returns:
        True si supprimé, False si non trouvé

    Raises:
        ValueError: Si tentative de suppression d'un rôle système
        ValueError: Si des utilisateurs ont encore ce rôle

    Example:
        >>> deleted = delete_role(db, 5)
    """
    db_role = get_role(db, role_id)

    if not db_role:
        return False

    # Empêcher la suppression des rôles système
    if db_role.is_system_role:
        raise ValueError("Les rôles système ne peuvent pas être supprimés")

    # Vérifier si des utilisateurs ont ce rôle
    if db_role.users:
        raise ValueError(
            f"Impossible de supprimer le rôle '{db_role.name}' : "
            f"{len(db_role.users)} utilisateur(s) l'utilise(nt) encore"
        )

    db.delete(db_role)
    db.commit()

    return True


def create_system_roles(db: Session) -> List[Role]:
    """
    Crée les rôles système prédéfinis s'ils n'existent pas.

    À appeler au démarrage de l'application pour initialiser les rôles.

    Args:
        db: Session de base de données

    Returns:
        Liste des rôles système créés ou existants

    Example:
        >>> system_roles = create_system_roles(db)
        >>> print([r.name for r in system_roles])
        ['super_admin', 'admin', 'user', 'viewer']
    """
    created_roles = []

    for role_name, permissions in ROLE_PERMISSIONS.items():
        # Vérifier si le rôle existe déjà
        existing_role = get_role_by_name(db, role_name)

        if existing_role:
            # Réconciliation de la dérive de permissions : ROLE_PERMISSIONS est
            # la source de vérité pour les rôles système. Sans cette mise à
            # jour, un déploiement initialisé AVANT un changement de matrice
            # conserve indéfiniment d'anciennes permissions (créer-si-absent ne
            # suffit pas). On ne touche qu'aux rôles système, champ permissions.
            if (
                existing_role.is_system_role
                and existing_role.permissions != permissions
            ):
                existing_role.permissions = permissions
            created_roles.append(existing_role)
            continue

        # Créer le rôle système
        db_role = Role(
            name=role_name,
            description=f"Rôle système : {role_name.replace('_', ' ').title()}",
            permissions=permissions,
            is_active=True,
            is_system_role=True
        )

        db.add(db_role)
        created_roles.append(db_role)

    db.commit()

    # Refresh tous les rôles créés
    for role in created_roles:
        db.refresh(role)

    return created_roles


def get_role_users_count(db: Session, role_id: int) -> int:
    """
    Compte le nombre d'utilisateurs ayant un rôle donné.

    Args:
        db: Session de base de données
        role_id: ID du rôle

    Returns:
        Nombre d'utilisateurs avec ce rôle

    Example:
        >>> count = get_role_users_count(db, 1)
        >>> print(f"Nombre d'admins : {count}")
    """
    db_role = get_role(db, role_id)

    if not db_role:
        return 0

    return len(db_role.users)
