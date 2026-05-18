"""
ShiftWise User Management Routes

Routes pour la gestion CRUD des utilisateurs :
- Création d'utilisateurs
- Listing avec pagination et filtres
- Mise à jour
- Suppression
- Gestion des rôles

Toutes les routes respectent le RBAC et le multi-tenancy.
"""

import math
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserRead,
    UserReadWithRoles,
    UserList
)
from app.schemas.auth import MessageResponse
from app.crud import user as crud_user
from app.crud import role as crud_role
from app.api.deps import (
    get_current_user,
    get_current_superuser,
    check_permission,
    get_current_user_tenant
)
from app.models.user import User
from app.models.role import Role

router = APIRouter()

# S1192 — Constantes pour éviter la duplication de littéraux
USER_NOT_FOUND = "Utilisateur non trouvé"
USER_ACCESS_DENIED = "Accès non autorisé à cet utilisateur"
SUPER_ADMIN_ROLE = "super_admin"
RESOURCE_USERS = "users"


def _check_privilege_escalation(current_user: User, role_ids: list[int], db: Session) -> None:
    """
    Vérifie qu'un non-superuser ne s'octroie (ni n'octroie) pas, via
    l'assignation de rôles, des permissions qu'il ne possède pas lui-même.

    Audit C-03 — modèle strict : chaque action de chaque rôle assigné doit
    déjà figurer dans les permissions effectives de l'appelant. La version
    précédente ne bloquait que les actions joker ("*"), laissant passer un
    rôle listant explicitement read/create/update/delete.

    Lève HTTPException 403 en cas de violation.
    """
    assigned_roles = db.query(Role).filter(Role.id.in_(role_ids)).all()

    for role in assigned_roles:
        if role.name == SUPER_ADMIN_ROLE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un super_admin peut assigner le rôle super_admin"
            )
        for resource, actions in (role.permissions or {}).items():
            for action in actions or []:
                if not current_user.has_permission(resource, action):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            "Vous ne pouvez pas assigner un rôle accordant "
                            f"'{resource}:{action}' — permission absente de votre compte"
                        ),
                    )


def _is_super_admin(user: User) -> bool:
    """
    True si l'utilisateur possède des privilèges super-admin — soit le flag
    is_superuser, soit le rôle super_admin. Un tel compte ne peut être géré
    que par un autre super-admin.
    """
    if user.is_superuser:
        return True
    return any(role.name == SUPER_ADMIN_ROLE for role in user.roles)


@router.post("", response_model=UserReadWithRoles, status_code=status.HTTP_201_CREATED)
def create_user(
        user_data: UserCreate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "create"))]
):
    # Vérification multi-tenancy
    if not current_user.is_superuser and user_data.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez créer des utilisateurs que dans votre propre tenant"
        )

    # Guard: prevent privilege escalation via role assignment at creation
    if not current_user.is_superuser and user_data.role_ids:
        _check_privilege_escalation(current_user, user_data.role_ids, db)

    try:
        return crud_user.create_user(db, user_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("", response_model=UserList)
def list_users(
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à sauter")] = 0,
        limit: Annotated[int, Query(ge=1, le=1000, description="Nombre d'éléments à retourner")] = 100,
        search: Annotated[Optional[str], Query(description="Rechercher dans email, username, nom")] = None,
        is_active: Annotated[Optional[bool], Query(description="Filtrer par statut actif")] = None,
        is_superuser: Annotated[Optional[bool], Query(description="Filtrer par superuser")] = None,
        tenant_id: Annotated[Optional[str], Query(description="Filtrer par tenant (superuser uniquement)")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "read"))] = None
):
    """
    Liste les utilisateurs avec pagination et filtres.

    **Permissions requises :** `users:read`

    **Multi-tenancy :**
    - Les admins voient uniquement les utilisateurs de leur tenant
    - Les superusers peuvent voir tous les tenants (avec filtre optionnel)

    **Pagination :**
    - `skip` : Décalage (par défaut 0)
    - `limit` : Nombre max d'éléments (par défaut 100, max 1000)

    **Filtres :**
    - `search` : Recherche dans email, username, first_name, last_name
    - `is_active` : true/false
    - `is_superuser` : true/false
    - `tenant_id` : Filtrer par tenant (superuser uniquement)

    **Example :**
    ```
    GET /api/v1/users?skip=0&limit=10&search=ahmed&is_active=true
    ```

    **Response :**
    ```json
    {
        "items": [...],
        "total": 50,
        "page": 1,
        "page_size": 10,
        "pages": 5
    }
    ```
    """
    # Multi-tenancy : forcer le tenant pour les non-superusers
    filter_tenant_id = tenant_id
    if not current_user.is_superuser:
        filter_tenant_id = current_user.tenant_id

    # Récupérer les utilisateurs
    users = crud_user.get_users(
        db,
        skip=skip,
        limit=limit,
        tenant_id=filter_tenant_id,
        is_active=is_active,
        is_superuser=is_superuser,
        search=search
    )

    # Compter le total
    total = crud_user.get_users_count(
        db,
        tenant_id=filter_tenant_id,
        is_active=is_active,
        is_superuser=is_superuser,
        search=search
    )

    # Calculer la pagination
    page = (skip // limit) + 1
    pages = math.ceil(total / limit) if limit > 0 else 0

    return UserList(
        items=[UserRead.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=limit,
        pages=pages
    )


@router.get("/tenant/{tenant_id}/count")
def count_users_by_tenant(
        tenant_id: str,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "read"))]
):
    """
    Compte le nombre d'utilisateurs dans un tenant.

    **Permissions requises :** `users:read`

    **Multi-tenancy :**
    - Les admins peuvent seulement compter dans leur propre tenant
    - Les superusers peuvent compter dans n'importe quel tenant

    **Example :**
    ```
    GET /api/v1/users/tenant/nextstep/count
    ```

    **Response :**
    ```json
    {
        "tenant_id": "nextstep",
        "total_users": 25,
        "active_users": 23,
        "inactive_users": 2
    }
    ```
    """
    # Vérification multi-tenancy
    if not current_user.is_superuser:
        if tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à ce tenant"
            )

    # Compter
    total = crud_user.get_users_count(db, tenant_id=tenant_id)
    active = crud_user.get_users_count(db, tenant_id=tenant_id, is_active=True)
    inactive = crud_user.get_users_count(db, tenant_id=tenant_id, is_active=False)

    return {
        "tenant_id": tenant_id,
        "total_users": total,
        "active_users": active,
        "inactive_users": inactive
    }


# ─── Dynamic routes (/{user_id}) — must be declared AFTER all static routes ───


@router.get("/{user_id}", response_model=UserReadWithRoles)
def get_user(
        user_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "read"))]
):
    """
    Récupère un utilisateur par son ID.

    **Permissions requises :** `users:read`

    **Multi-tenancy :**
    - Les admins ne peuvent voir que les utilisateurs de leur tenant
    - Les superusers peuvent voir tous les utilisateurs

    **Example :**
    ```
    GET /api/v1/users/1
    ```
    """
    user = crud_user.get_user(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=USER_NOT_FOUND
        )

    # Vérification multi-tenancy
    if not current_user.is_superuser:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=USER_ACCESS_DENIED
            )

    return user


@router.put("/{user_id}", response_model=UserReadWithRoles)
def update_user(
        user_id: int,
        user_update: UserUpdate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "update"))]
):
    """
    Met à jour un utilisateur.

    **Permissions requises :** `users:update`

    **Multi-tenancy :**
    - Les admins ne peuvent modifier que les utilisateurs de leur tenant
    - Les superusers peuvent modifier tous les utilisateurs
    - Un utilisateur peut toujours se modifier lui-même

    **Champs modifiables :**
    - email, username, first_name, last_name
    - password (hashé automatiquement)
    - is_active
    - role_ids (nécessite permission users:update)

    **Example :**
    ```json
    PUT /api/v1/users/1
    {
        "first_name": "Ahmed Habib",
        "is_active": true
    }
    ```
    """
    user = crud_user.get_user(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=USER_NOT_FOUND
        )

    # Vérification multi-tenancy
    # Un utilisateur peut se modifier lui-même
    # Sinon, vérification du tenant
    if user_id != current_user.id and not current_user.is_superuser:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=USER_ACCESS_DENIED
            )

    # Un non-superuser ne peut pas modifier un compte super-admin
    # (sauf son propre compte).
    if (
        user_id != current_user.id
        and not current_user.is_superuser
        and _is_super_admin(user)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un super_admin peut modifier un compte super_admin"
        )

    # Audit C-04 : un non-superuser modifiant son PROPRE compte ne peut pas
    # toucher à ses rôles (vecteur d'auto-escalade) — les changements de rôle
    # passent par un administrateur.
    if (
        user_id == current_user.id
        and not current_user.is_superuser
        and user_update.role_ids is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas modifier vos propres rôles"
        )

    # Audit H-06 : changer son PROPRE mot de passe exige une ré-authentification
    # (vérification du mot de passe actuel) — passer par /auth/change-password.
    # PUT /users/{id} reste utilisable par un admin pour réinitialiser le mot
    # de passe d'un AUTRE utilisateur.
    if user_update.password is not None and user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pour changer votre propre mot de passe, utilisez "
                   "/api/v1/auth/change-password (mot de passe actuel requis)"
        )

    # Guard : empêche l'escalade de privilèges via l'assignation de rôles.
    if not current_user.is_superuser and user_update.role_ids:
        _check_privilege_escalation(current_user, user_update.role_ids, db)

    # Mettre à jour
    try:
        updated_user = crud_user.update_user(db, user_id, user_update)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    return updated_user


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(
        user_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "delete"))]
):
    """
    Supprime un utilisateur.

    **Permissions requises :** `users:delete`

    **Multi-tenancy :**
    - Les admins ne peuvent supprimer que les utilisateurs de leur tenant
    - Les superusers peuvent supprimer tous les utilisateurs

    **Protections :**
    - Impossible de se supprimer soi-même

    **Example :**
    ```
    DELETE /api/v1/users/5
    ```
    """
    # Impossible de se supprimer soi-même.
    # Audit B-23 : un refus de cette opération est une interdiction
    # d'autorisation — 403, pas 400 (la requête est bien formée).
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Impossible de supprimer votre propre compte"
        )

    user = crud_user.get_user(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=USER_NOT_FOUND
        )

    # Vérification multi-tenancy
    if not current_user.is_superuser:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=USER_ACCESS_DENIED
            )

    # Un non-superuser ne peut pas supprimer un compte super-admin.
    if not current_user.is_superuser and _is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un super_admin peut supprimer un compte super_admin"
        )

    # Supprimer
    crud_user.delete_user(db, user_id)

    return MessageResponse(
        message=f"Utilisateur {user.email} supprimé avec succès",
        success=True
    )


@router.post("/{user_id}/roles/{role_id}", response_model=UserReadWithRoles)
def add_role_to_user(
        user_id: int,
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "update"))]
):
    """
    Ajoute un rôle à un utilisateur.

    **Permissions requises :** `users:update`

    **Multi-tenancy :**
    - Les admins ne peuvent modifier que les utilisateurs de leur tenant
    - Les superusers peuvent modifier tous les utilisateurs

    **Example :**
    ```
    POST /api/v1/users/1/roles/2
    ```
    """
    user = crud_user.get_user(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=USER_NOT_FOUND
        )

    # Vérification multi-tenancy
    if not current_user.is_superuser:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=USER_ACCESS_DENIED
            )

    # Vérifier que le rôle existe
    role = crud_role.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rôle non trouvé"
        )

    # Audit C-04 : un non-superuser ne peut pas s'attribuer un rôle à
    # lui-même (la gestion des rôles est une fonction d'administration).
    if user_id == current_user.id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas modifier vos propres rôles"
        )

    # Audit C-03 : empêche l'escalade de privilèges via l'assignation de rôle.
    if not current_user.is_superuser:
        _check_privilege_escalation(current_user, [role_id], db)

    # Ajouter le rôle
    updated_user = crud_user.add_role_to_user(db, user_id, role_id)

    return updated_user


@router.delete("/{user_id}/roles/{role_id}", response_model=UserReadWithRoles)
def remove_role_from_user(
        user_id: int,
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_USERS, "update"))]
):
    """
    Retire un rôle d'un utilisateur.

    **Permissions requises :** `users:update`

    **Multi-tenancy :**
    - Les admins ne peuvent modifier que les utilisateurs de leur tenant
    - Les superusers peuvent modifier tous les utilisateurs

    **Example :**
    ```
    DELETE /api/v1/users/1/roles/2
    ```
    """
    user = crud_user.get_user(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=USER_NOT_FOUND
        )

    # Vérification multi-tenancy
    if not current_user.is_superuser:
        if user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=USER_ACCESS_DENIED
            )

    # Audit B-10 : refuser de laisser un compte sans aucun rôle. Un
    # utilisateur sans rôle perd toute permission et devient ingérable via
    # l'API (plus aucune route protégée n'est accessible). La garde ne se
    # déclenche que si le rôle visé est bien le dernier réellement attaché.
    current_role_ids = {role.id for role in user.roles}
    if role_id in current_role_ids and len(current_role_ids) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de retirer le dernier rôle d'un utilisateur"
        )

    # Retirer le rôle
    updated_user = crud_user.remove_role_from_user(db, user_id, role_id)

    return updated_user