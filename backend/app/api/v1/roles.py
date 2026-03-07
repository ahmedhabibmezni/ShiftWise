"""
ShiftWise Role Management Routes

Routes pour la gestion CRUD des rôles :
- Création de rôles personnalisés
- Listing des rôles
- Mise à jour des permissions
- Suppression (avec protections pour rôles système)
- Statistiques d'utilisation

Les rôles système (super_admin, admin, user, viewer) ne peuvent pas être modifiés.
"""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.role import (
    RoleCreate,
    RoleUpdate,
    RoleRead,
    RoleWithUsers
)
from app.schemas.auth import MessageResponse
from app.crud import role as crud_role
from app.api.deps import (
    get_current_user,
    get_current_superuser,
    check_permission
)
from app.models.user import User

router = APIRouter()

# S1192 — Constante pour éviter la duplication du littéral
ROLE_NOT_FOUND = "Rôle non trouvé"


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
        role_data: RoleCreate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "create"))]
):
    """
    Crée un nouveau rôle personnalisé.

    **Permissions requises :** `roles:create`

    **Note :** Seuls les rôles personnalisés peuvent être créés.
    Les rôles système (super_admin, admin, user, viewer) sont prédéfinis.

    **Validations :**
    - Nom unique (minuscules, alphanumerique + underscores)
    - Permissions valides (resources et actions autorisées)

    **Example :**
    ```json
    POST /api/v1/roles
    {
        "name": "project_manager",
        "description": "Gestionnaire de projets de migration",
        "permissions": {
            "vms": ["read", "create", "update"],
            "migrations": ["read", "create"],
            "reports": ["read"]
        },
        "is_active": true
    }
    ```

    **Permissions valides :**
    - Resources : vms, hypervisors, migrations, reports, users, roles, settings
    - Actions : create, read, update, delete, * (toutes)
    """
    try:
        new_role = crud_role.create_role(db, role_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    return new_role


@router.get("", response_model=list[RoleRead])
def list_roles(
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à sauter")] = 0,
        limit: Annotated[int, Query(ge=1, le=1000, description="Nombre d'éléments à retourner")] = 100,
        is_active: Annotated[Optional[bool], Query(description="Filtrer par statut actif")] = None,
        search: Annotated[Optional[str], Query(description="Rechercher dans nom et description")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("roles", "read"))] = None
):
    """
    Liste tous les rôles avec pagination et filtres.

    **Permissions requises :** `roles:read`

    **Filtres :**
    - `is_active` : true/false (afficher uniquement les rôles actifs/inactifs)
    - `search` : Recherche dans le nom et la description

    **Example :**
    ```
    GET /api/v1/roles?is_active=true&search=admin
    ```

    **Response :**
    ```json
    [
        {
            "id": 1,
            "name": "admin",
            "description": "Administrateur avec accès complet au tenant",
            "permissions": {
                "vms": ["*"],
                "hypervisors": ["*"],
                "migrations": ["*"]
            },
            "is_system_role": true,
            "is_active": true,
            "created_at": "2026-01-30T10:00:00",
            "updated_at": "2026-01-30T10:00:00"
        }
    ]
    ```
    """
    roles = crud_role.get_roles(
        db,
        skip=skip,
        limit=limit,
        is_active=is_active,
        search=search
    )

    return roles


@router.get("/count")
def count_roles(
        is_active: Annotated[Optional[bool], Query(description="Filtrer par statut actif")] = None,
        search: Annotated[Optional[str], Query(description="Rechercher")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission("roles", "read"))] = None
):
    """
    Compte le nombre total de rôles.

    **Permissions requises :** `roles:read`

    **Example :**
    ```
    GET /api/v1/roles/count?is_active=true
    ```

    **Response :**
    ```json
    {
        "total": 6,
        "system_roles": 4,
        "custom_roles": 2
    }
    ```
    """
    total = crud_role.get_roles_count(db, is_active=is_active, search=search)

    # Compter les rôles système vs personnalisés
    all_roles = crud_role.get_roles(db, skip=0, limit=1000)
    system_count = sum(1 for r in all_roles if r.is_system_role)
    custom_count = total - system_count

    return {
        "total": total,
        "system_roles": system_count,
        "custom_roles": custom_count
    }



@router.get("/name/{role_name}", response_model=RoleRead)
def get_role_by_name(
        role_name: str,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "read"))]
):
    """
    Récupère un rôle par son nom.

    **Permissions requises :** `roles:read`

    **Example :**
    ```
    GET /api/v1/roles/name/admin
    ```
    """
    role = crud_role.get_role_by_name(db, role_name)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rôle '{role_name}' non trouvé"
        )

    return role


@router.post("/init-system-roles", response_model=MessageResponse)
def initialize_system_roles(
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_superuser)]
):
    """
    Initialise les rôles système prédéfinis.

    **Permissions requises :** Superuser uniquement

    Crée les rôles système s'ils n'existent pas :
    - super_admin : Accès complet au système
    - admin : Gestion complète du tenant
    - user : Accès aux ressources assignées
    - viewer : Lecture seule

    **Note :** Cette route doit être appelée une seule fois lors de
    l'initialisation de l'application. Elle est idempotente (peut être
    appelée plusieurs fois sans effet secondaire).

    **Example :**
    ```
    POST /api/v1/roles/init-system-roles
    ```

    **Response :**
    ```json
    {
        "message": "4 rôles système initialisés avec succès",
        "success": true
    }
    ```
    """
    created_roles = crud_role.create_system_roles(db)

    return MessageResponse(
        message=f"{len(created_roles)} rôles système initialisés avec succès",
        success=True
    )


@router.get("/permissions/resources")
def list_available_resources(
        current_user: Annotated[User, Depends(check_permission("roles", "read"))]
):
    """
    Liste les ressources disponibles pour les permissions.

    **Permissions requises :** `roles:read`

    Retourne la liste des ressources qui peuvent être utilisées
    dans les permissions des rôles.

    **Example :**
    ```
    GET /api/v1/roles/permissions/resources
    ```

    **Response :**
    ```json
    {
        "resources": [
            "vms",
            "hypervisors",
            "migrations",
            "reports",
            "users",
            "roles",
            "settings"
        ],
        "actions": [
            "create",
            "read",
            "update",
            "delete",
            "*"
        ]
    }
    ```
    """
    return {
        "resources": [
            "vms",
            "hypervisors",
            "migrations",
            "reports",
            "users",
            "roles",
            "settings"
        ],
        "actions": [
            "create",
            "read",
            "update",
            "delete",
            "*"
        ],
        "description": {
            "vms": "Machines virtuelles",
            "hypervisors": "Hyperviseurs sources",
            "migrations": "Opérations de migration",
            "reports": "Rapports et journaux",
            "users": "Gestion des utilisateurs",
            "roles": "Gestion des rôles",
            "settings": "Paramètres système"
        }
    }


# ─── Dynamic routes (/{role_id}) — must be declared AFTER all static routes ───


@router.get("/{role_id}", response_model=RoleWithUsers)
def get_role(
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "read"))]
):
    """
    Récupère un rôle par son ID avec le nombre d'utilisateurs.

    **Permissions requises :** `roles:read`

    **Example :**
    ```
    GET /api/v1/roles/1
    ```

    **Response :**
    ```json
    {
        "id": 1,
        "name": "admin",
        "description": "Administrateur",
        "permissions": {"vms": ["*"]},
        "is_system_role": true,
        "is_active": true,
        "user_count": 5,
        "created_at": "2026-01-30T10:00:00",
        "updated_at": "2026-01-30T10:00:00"
    }
    ```
    """
    role = crud_role.get_role(db, role_id)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ROLE_NOT_FOUND
        )

    # Compter les utilisateurs
    user_count = crud_role.get_role_users_count(db, role_id)

    # Construire la réponse
    role_data = RoleWithUsers.model_validate(role)
    role_data.user_count = user_count

    return role_data


@router.put("/{role_id}", response_model=RoleRead)
def update_role(
        role_id: int,
        role_update: RoleUpdate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "update"))]
):
    """
    Met à jour un rôle personnalisé.

    **Permissions requises :** `roles:update`

    **Protection :** Les rôles système ne peuvent pas être modifiés.

    **Champs modifiables :**
    - name (si pas déjà utilisé)
    - description
    - permissions
    - is_active

    **Example :**
    ```json
    PUT /api/v1/roles/5
    {
        "description": "Nouvelle description",
        "permissions": {
            "vms": ["read", "create"],
            "migrations": ["read"]
        }
    }
    ```
    """
    try:
        updated_role = crud_role.update_role(db, role_id, role_update)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not updated_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ROLE_NOT_FOUND
        )

    return updated_role


@router.delete("/{role_id}", response_model=MessageResponse)
def delete_role(
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "delete"))]
):
    """
    Supprime un rôle personnalisé.

    **Permissions requises :** `roles:delete`

    **Protections :**
    - Les rôles système ne peuvent pas être supprimés
    - Un rôle avec des utilisateurs assignés ne peut pas être supprimé

    **Example :**
    ```
    DELETE /api/v1/roles/5
    ```

    **Response :**
    ```json
    {
        "message": "Rôle 'project_manager' supprimé avec succès",
        "success": true
    }
    ```
    """
    role = crud_role.get_role(db, role_id)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ROLE_NOT_FOUND
        )

    try:
        deleted = crud_role.delete_role(db, role_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ROLE_NOT_FOUND
            )

        return MessageResponse(
            message=f"Rôle '{role.name}' supprimé avec succès",
            success=True
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{role_id}/users/count")
def get_role_user_count(
        role_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(check_permission("roles", "read"))]
):
    """
    Compte le nombre d'utilisateurs ayant un rôle donné.

    **Permissions requises :** `roles:read`

    **Example :**
    ```
    GET /api/v1/roles/1/users/count
    ```

    **Response :**
    ```json
    {
        "role_id": 1,
        "role_name": "admin",
        "user_count": 5
    }
    ```
    """
    role = crud_role.get_role(db, role_id)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ROLE_NOT_FOUND
        )

    count = crud_role.get_role_users_count(db, role_id)

    return {
        "role_id": role_id,
        "role_name": role.name,
        "user_count": count
    }