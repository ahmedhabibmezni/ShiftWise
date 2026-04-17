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


def _check_privilege_escalation(current_user: User, role_ids: list[int], db: Session) -> None:
    """
    Vérifie qu'un non-superuser ne s'octroie pas des permissions supérieures
    aux siennes via l'assignation de rôles.
    Lève HTTPException 403 en cas de violation.
    """
    assigned_roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    admin_permissions = current_user.get_all_permissions()

    for role in assigned_roles:
        if role.name == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul un super_admin peut assigner le rôle super_admin"
            )
        for resource, actions in (role.permissions or {}).items():
            if "*" in actions and resource not in admin_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Vous ne pouvez pas assigner un rôle avec accès complet à '{resource}'"
                )

@router.post("", response_model=UserReadWithRoles, status_code=status.HTTP_201_CREATED)
def create_user(
        user_data: UserCreate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("users", "create"))]
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
        current_user: Annotated[User, Depends(check_permission("users", "read"))] = None
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
        current_user: Annotated[User, Depends(check_permission("users", "read"))]
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
        current_user: Annotated[User, Depends(check_permission("users", "read"))]
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
        current_user: Annotated[User, Depends(check_permission("users", "update"))]
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
        current_user: Annotated[User, Depends(check_permission("users", "delete"))]
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
    # Impossible de se supprimer soi-même
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
        current_user: Annotated[User, Depends(check_permission("users", "update"))]
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

    # Guard: prevent privilege escalation
    if role.name == "super_admin" and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un super_admin peut assigner le rôle super_admin"
        )

    if not current_user.is_superuser:
        admin_permissions = current_user.get_all_permissions()
        for resource, actions in (role.permissions or {}).items():
            if "*" in actions and resource not in admin_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Vous ne pouvez pas assigner un rôle avec accès complet à '{resource}'"
                )

    # Ajouter le rôle
    updated_user = crud_user.add_role_to_user(db, user_id, role_id)

    return updated_user


@router.delete("/{user_id}/roles/{role_id}", response_model=UserReadWithRoles)
def remove_role_from_user(
        user_id: int,
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("users", "update"))]
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

    # Retirer le rôle
    updated_user = crud_user.remove_role_from_user(db, user_id, role_id)

    return updated_user