"""
ShiftWise Role Schemas

Schémas Pydantic pour la validation des données de Role.

Les schémas définissent :
- Ce qui peut être envoyé à l'API (Create, Update)
- Ce qui est retourné par l'API (Read)
- La validation automatique des données
"""

from typing import Optional, Dict, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import VALID_ACTIONS


class RoleBase(BaseModel):
    """
    Schéma de base pour Role.

    Contient les champs communs à tous les schémas Role.
    """
    name: str = Field(
        ...,
        min_length=2,
        max_length=50,
        description="Nom unique du rôle",
        json_schema_extra={"example": "admin"}
    )

    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Description du rôle",
        json_schema_extra={"example": "Administrateur avec accès complet au tenant"}
    )

    permissions: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Permissions du rôle par ressource",
        json_schema_extra={"example": {"vms": ["read", "create", "update", "delete"], "hypervisors": ["read", "create"]}}
    )

    is_active: bool = Field(
        default=True,
        description="Indique si le rôle est actif"
    )

    @field_validator('name')
    def validate_name(cls, v: str) -> str:
        """
        Valide le nom du rôle.

        - Doit être en minuscules
        - Peut contenir des lettres, chiffres, et underscores
        """
        if not v.replace('_', '').isalnum():
            raise ValueError("Le nom du rôle ne peut contenir que des lettres, chiffres et underscores")
        return v.lower()

    @field_validator('permissions')
    def validate_permissions(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Valide la structure des permissions.

        Vérifie que chaque ressource a une liste d'actions valides.
        """
        for resource, actions in v.items():
            if not isinstance(actions, list):
                raise ValueError(f"Les actions pour '{resource}' doivent être une liste")

            for action in actions:
                if action not in VALID_ACTIONS:
                    raise ValueError(
                        f"Action invalide '{action}' pour '{resource}'. "
                        f"Actions valides: {VALID_ACTIONS}"
                    )

        return v


class RoleCreate(RoleBase):
    """
    Schéma pour la création d'un rôle.

    Utilisé lors de POST /api/v1/roles
    """
    pass


class RoleUpdate(BaseModel):
    """
    Schéma pour la mise à jour d'un rôle.

    Tous les champs sont optionnels.
    Utilisé lors de PUT/PATCH /api/v1/roles/{id}
    """
    name: Optional[str] = Field(
        None,
        min_length=2,
        max_length=50,
        description="Nom du rôle"
    )

    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Description du rôle"
    )

    permissions: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Permissions du rôle"
    )

    is_active: Optional[bool] = Field(
        None,
        description="Statut actif/inactif"
    )

    @field_validator('name')
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Valide le nom si fourni"""
        if v is not None:
            if not v.replace('_', '').isalnum():
                raise ValueError("Le nom du rôle ne peut contenir que des lettres, chiffres et underscores")
            return v.lower()
        return v


class RoleInDB(RoleBase):
    """
    Schéma représentant un rôle en base de données.

    Inclut tous les champs de la BDD.
    """
    id: int
    is_system_role: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RoleRead(RoleInDB):
    """
    Schéma pour la lecture d'un rôle.

    Retourné par l'API lors de GET /api/v1/roles
    """
    pass


class RoleWithUsers(RoleRead):
    """
    Schéma incluant la liste des utilisateurs ayant ce rôle.

    Utilisé pour les endpoints nécessitant ces informations.
    """
    user_count: int = Field(
        default=0,
        description="Nombre d'utilisateurs ayant ce rôle"
    )

    model_config = ConfigDict(from_attributes=True)