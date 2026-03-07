"""
ShiftWise User CRUD Operations

Opérations CRUD (Create, Read, Update, Delete) pour les utilisateurs.

Inclut la gestion multi-tenancy et RBAC.
"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.user import User
from app.models.role import Role
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash, verify_password


def get_user(db: Session, user_id: int) -> Optional[User]:
    """
    Récupère un utilisateur par son ID.

    Args:
        db: Session de base de données
        user_id: ID de l'utilisateur

    Returns:
        User si trouvé, None sinon

    Example:
        >>> user = get_user(db, 1)
        >>> print(user.email)
    """
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """
    Récupère un utilisateur par son email.

    Args:
        db: Session de base de données
        email: Email de l'utilisateur

    Returns:
        User si trouvé, None sinon

    Example:
        >>> user = get_user_by_email(db, "ahmed@nextstep.tn")
    """
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """
    Récupère un utilisateur par son nom d'utilisateur.

    Args:
        db: Session de base de données
        username: Nom d'utilisateur

    Returns:
        User si trouvé, None sinon

    Example:
        >>> user = get_user_by_username(db, "ahmedm")
    """
    return db.query(User).filter(User.username == username.lower()).first()


def get_users(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        tenant_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_superuser: Optional[bool] = None,
        search: Optional[str] = None
) -> List[User]:
    """
    Récupère une liste d'utilisateurs avec filtres et pagination.

    Args:
        db: Session de base de données
        skip: Nombre d'éléments à sauter (pagination)
        limit: Nombre maximum d'éléments à retourner
        tenant_id: Filtrer par tenant (optionnel)
        is_active: Filtrer par statut actif/inactif (optionnel)
        is_superuser: Filtrer par superuser (optionnel)
        search: Rechercher dans email, username, nom (optionnel)

    Returns:
        Liste d'utilisateurs

    Example:
        >>> users = get_users(db, tenant_id="nextstep", is_active=True)
        >>> users = get_users(db, search="ahmed")
    """
    query = db.query(User)

    # Filtre par tenant (multi-tenancy)
    if tenant_id:
        query = query.filter(User.tenant_id == tenant_id)

    # Filtre par statut actif
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    # Filtre par superuser
    if is_superuser is not None:
        query = query.filter(User.is_superuser == is_superuser)

    # Recherche dans email, username, prénom, nom
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(search_term),
                User.username.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term)
            )
        )

    return query.offset(skip).limit(limit).all()


def get_users_count(
        db: Session,
        tenant_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_superuser: Optional[bool] = None,
        search: Optional[str] = None
) -> int:
    """
    Compte le nombre total d'utilisateurs avec les mêmes filtres.

    Args:
        db: Session de base de données
        tenant_id: Filtrer par tenant
        is_active: Filtrer par statut actif/inactif
        is_superuser: Filtrer par superuser
        search: Rechercher dans les champs

    Returns:
        Nombre d'utilisateurs correspondants
    """
    query = db.query(User)

    if tenant_id:
        query = query.filter(User.tenant_id == tenant_id)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    if is_superuser is not None:
        query = query.filter(User.is_superuser == is_superuser)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(search_term),
                User.username.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term)
            )
        )

    return query.count()


def create_user(db: Session, user: UserCreate) -> User:
    """
    Crée un nouvel utilisateur.

    Args:
        db: Session de base de données
        user: Données de l'utilisateur à créer (UserCreate schema)

    Returns:
        User créé

    Raises:
        ValueError: Si email ou username existe déjà
        ValueError: Si un role_id n'existe pas

    Example:
        >>> user_data = UserCreate(
        ...     email="ahmed@nextstep.tn",
        ...     username="ahmedm",
        ...     password="SecurePass123!",
        ...     tenant_id="nextstep",
        ...     role_ids=[1, 2]
        ... )
        >>> new_user = create_user(db, user_data)
    """
    # Vérifier si l'email existe déjà
    existing_user = get_user_by_email(db, user.email)
    if existing_user:
        raise ValueError(f"L'email '{user.email}' est déjà utilisé")

    # Vérifier si le username existe déjà
    existing_user = get_user_by_username(db, user.username)
    if existing_user:
        raise ValueError(f"Le nom d'utilisateur '{user.username}' est déjà utilisé")

    # Récupérer les rôles
    roles = []
    if user.role_ids:
        roles = db.query(Role).filter(Role.id.in_(user.role_ids)).all()

        # Vérifier que tous les rôles existent
        if len(roles) != len(user.role_ids):
            found_ids = {r.id for r in roles}
            missing_ids = set(user.role_ids) - found_ids
            raise ValueError(f"Rôles introuvables : {missing_ids}")

    # Hasher le mot de passe
    hashed_password = get_password_hash(user.password)

    # Créer l'utilisateur
    db_user = User(
        email=user.email.lower(),
        username=user.username.lower(),
        first_name=user.first_name,
        last_name=user.last_name,
        hashed_password=hashed_password,
        tenant_id=user.tenant_id.lower(),
        is_active=user.is_active,
        is_verified=False,  # À vérifier par email
        is_superuser=False  # Ne peut pas créer de superuser via API
    )

    # Assigner les rôles
    db_user.roles = roles

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


def _handle_email_update(db: Session, db_user: User, update_data: dict) -> None:
    """Gère la mise à jour de l'email avec vérification d'unicité."""
    new_email = update_data["email"].lower()
    if new_email != db_user.email:
        if get_user_by_email(db, new_email):
            raise ValueError(f"L'email '{new_email}' est déjà utilisé")
        update_data["email"] = new_email


def _handle_username_update(db: Session, db_user: User, update_data: dict) -> None:
    """Gère la mise à jour de 'username' avec vérification d'unicité."""
    new_username = update_data["username"].lower()
    if new_username != db_user.username:
        if get_user_by_username(db, new_username):
            raise ValueError(f"Le nom d'utilisateur '{new_username}' est déjà utilisé")
        update_data["username"] = new_username


def _handle_roles_update(db: Session, db_user: User, update_data: dict) -> None:
    """Gère la mise à jour des rôles avec vérification d'existence."""
    role_ids = update_data.pop("role_ids")
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    if len(roles) != len(role_ids):
        missing_ids = set(role_ids) - {r.id for r in roles}
        raise ValueError(f"Rôles introuvables : {missing_ids}")
    db_user.roles = roles


def update_user(
        db: Session,
        user_id: int,
        user_update: UserUpdate
) -> Optional[User]:
    """
    Met à jour un utilisateur existant.
    Args:
        db: Session de base de données
        user_id: ID de l'utilisateur à mettre à jour
        user_update: Données à mettre à jour (UserUpdate schema)
    Returns:
        User mis à jour si trouvé, None sinon
    Raises:
        ValueError: Si le nouvel email/username existe déjà
        ValueError: Si un role_id n'existe pas
    Example:
        >>> update_data = UserUpdate(first_name="Ahmed Habib")
        >>> updated_user = update_user(db, 1, update_data)
    """
    db_user = get_user(db, user_id)
    if not db_user:
        return None

    update_data = user_update.model_dump(exclude_unset=True)

    if "email" in update_data:
        _handle_email_update(db, db_user, update_data)

    if "username" in update_data:
        _handle_username_update(db, db_user, update_data)

    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

    if "role_ids" in update_data:
        _handle_roles_update(db, db_user, update_data)

    for field, value in update_data.items():
        setattr(db_user, field, value)

    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    """
    Supprime un utilisateur.

    Args:
        db: Session de base de données
        user_id: ID de l'utilisateur à supprimer

    Returns:
        True si supprimé, False si non trouvé

    Example:
        >>> deleted = delete_user(db, 5)
    """
    db_user = get_user(db, user_id)

    if not db_user:
        return False

    db.delete(db_user)
    db.commit()

    return True


def authenticate_user(
        db: Session,
        email: str,
        password: str
) -> Optional[User]:
    """
    Authentifie un utilisateur par email et mot de passe.

    Args:
        db: Session de base de données
        email: Email de l'utilisateur
        password: Mot de passe en clair

    Returns:
        User si authentification réussie, None sinon

    Example:
        >>> user = authenticate_user(db, "ahmed@nextstep.tn", "MyPassword123!")
        >>> if user:
        ...     print("Login réussi")
    """
    user = get_user_by_email(db, email)

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


def get_users_by_tenant(
        db: Session,
        tenant_id: str,
        skip: int = 0,
        limit: int = 100
) -> List[User]:
    """
    Récupère tous les utilisateurs d'un tenant (multi-tenancy).

    Args:
        db: Session de base de données
        tenant_id: ID du tenant
        skip: Pagination
        limit: Limite

    Returns:
        Liste des utilisateurs du tenant

    Example:
        >>> users = get_users_by_tenant(db, "nextstep")
    """
    return (
        db.query(User)
        .filter(User.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def add_role_to_user(db: Session, user_id: int, role_id: int) -> Optional[User]:
    """
    Ajoute un rôle à un utilisateur.

    Args:
        db: Session de base de données
        user_id: ID de l'utilisateur
        role_id: ID du rôle à ajouter

    Returns:
        User mis à jour, None si user ou role non trouvé

    Example:
        >>> user = add_role_to_user(db, 1, 2)
    """
    user = get_user(db, user_id)
    if not user:
        return None

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return None

    # Ajouter le rôle s'il ne l'a pas déjà
    if role not in user.roles:
        user.roles.append(role)
        db.commit()
        db.refresh(user)

    return user


def remove_role_from_user(db: Session, user_id: int, role_id: int) -> Optional[User]:
    """
    Retire un rôle d'un utilisateur.

    Args:
        db: Session de base de données
        user_id: ID de l'utilisateur
        role_id: ID du rôle à retirer

    Returns:
        User mis à jour, None si user non trouvé

    Example:
        >>> user = remove_role_from_user(db, 1, 2)
    """
    user = get_user(db, user_id)
    if not user:
        return None

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return user

    # Retirer le rôle s'il l'a
    if role in user.roles:
        user.roles.remove(role)
        db.commit()
        db.refresh(user)

    return user