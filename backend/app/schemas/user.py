"""
ShiftWise User Schemas

Schémas Pydantic pour la validation des données utilisateur.

Inclut :
- Création d'utilisateur
- Mise à jour d'utilisateur
- Lecture d'utilisateur (avec rôles et permissions)
- Validation email, mot de passe, etc.
"""

from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, validator, field_validator
import re

from app.schemas.role import RoleRead


class UserBase(BaseModel):
    """
    Schéma de base pour User.

    Contient les champs communs à tous les schémas User.
    """
    email: EmailStr = Field(
        ...,
        description="Email de l'utilisateur (identifiant unique)",
        example="ahmed.mezni@nextstep.tn"
    )

    username: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Nom d'utilisateur unique",
        example="ahmedm"
    )

    first_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Prénom de l'utilisateur",
        example="Ahmed"
    )

    last_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Nom de famille de l'utilisateur",
        example="MEZNI"
    )

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifiant du tenant (organisation)",
        example="nextstep-tunisia"
    )

    is_active: bool = Field(
        default=True,
        description="Indique si le compte est actif"
    )

    @field_validator('username')
    def validate_username(cls, v: str) -> str:
        """
        Valide le nom d'utilisateur.

        - Doit commencer par une lettre
        - Peut contenir lettres, chiffres, points, underscores, tirets
        - Pas d'espaces
        """
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9._-]*$', v):
            raise ValueError(
                "Le nom d'utilisateur doit commencer par une lettre et ne peut contenir "
                "que des lettres, chiffres, points, underscores et tirets"
            )
        return v.lower()

    @field_validator('tenant_id')
    def validate_tenant_id(cls, v: str) -> str:
        """Valide le tenant_id (format slug)"""
        if not re.match(r'^[a-z0-9-]+$', v.lower()):
            raise ValueError(
                "Le tenant_id ne peut contenir que des lettres minuscules, "
                "chiffres et tirets"
            )
        return v.lower()


class UserCreate(UserBase):
    """
    Schéma pour la création d'un utilisateur.

    Inclut le mot de passe en clair (sera hashé avant stockage).
    Utilisé lors de POST /api/v1/users
    """
    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="Mot de passe (minimum 8 caractères)",
        example="SecurePassword123!"
    )

    role_ids: List[int] = Field(
        default_factory=list,
        description="Liste des IDs de rôles à assigner",
        example=[1, 2]
    )

    @field_validator('password')
    def validate_password(cls, v: str) -> str:
        """
        Valide la robustesse du mot de passe.

        Exigences :
        - Minimum 8 caractères
        - Au moins une lettre majuscule
        - Au moins une lettre minuscule
        - Au moins un chiffre
        - Au moins un caractère spécial
        """
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")

        if not re.search(r'[A-Z]', v):
            raise ValueError("Le mot de passe doit contenir au moins une lettre majuscule")

        if not re.search(r'[a-z]', v):
            raise ValueError("Le mot de passe doit contenir au moins une lettre minuscule")

        if not re.search(r'\d', v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError("Le mot de passe doit contenir au moins un caractère spécial")

        return v


class UserUpdate(BaseModel):
    """
    Schéma pour la mise à jour d'un utilisateur.

    Tous les champs sont optionnels.
    Utilisé lors de PUT/PATCH /api/v1/users/{id}
    """
    email: Optional[EmailStr] = Field(
        None,
        description="Email de l'utilisateur"
    )

    username: Optional[str] = Field(
        None,
        min_length=3,
        max_length=100,
        description="Nom d'utilisateur"
    )

    first_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Prénom"
    )

    last_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Nom de famille"
    )

    password: Optional[str] = Field(
        None,
        min_length=8,
        max_length=100,
        description="Nouveau mot de passe"
    )

    is_active: Optional[bool] = Field(
        None,
        description="Statut actif/inactif"
    )

    role_ids: Optional[List[int]] = Field(
        None,
        description="Mise à jour des rôles"
    )

    @field_validator('username')
    def validate_username(cls, v: Optional[str]) -> Optional[str]:
        """Valide le username si fourni"""
        if v is not None:
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9._-]*$', v):
                raise ValueError("Format de nom d'utilisateur invalide")
            return v.lower()
        return v

    @field_validator('password')
    def validate_password(cls, v: Optional[str]) -> Optional[str]:
        """Valide le mot de passe si fourni"""
        if v is not None:
            if len(v) < 8:
                raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
            if not re.search(r'[A-Z]', v):
                raise ValueError("Le mot de passe doit contenir au moins une majuscule")
            if not re.search(r'[a-z]', v):
                raise ValueError("Le mot de passe doit contenir au moins une minuscule")
            if not re.search(r'\d', v):
                raise ValueError("Le mot de passe doit contenir au moins un chiffre")
            if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
                raise ValueError("Le mot de passe doit contenir un caractère spécial")
        return v


class UserInDB(UserBase):
    """
    Schéma représentant un utilisateur en base de données.

    Inclut tous les champs de la BDD (y compris hashed_password).
    """
    id: int
    hashed_password: str
    is_verified: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        """Configuration Pydantic"""
        from_attributes = True


class UserRead(BaseModel):
    """
    Schéma pour la lecture d'un utilisateur.

    Retourné par l'API - SANS le mot de passe hashé.
    Utilisé lors de GET /api/v1/users
    """
    id: int
    email: EmailStr
    username: str
    first_name: Optional[str]= None
    last_name: Optional[str]= None
    full_name: str  # Calculé automatiquement par le modèle
    tenant_id: str
    is_active: bool
    is_verified: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserReadWithRoles(UserRead):
    """
    Schéma incluant les rôles de l'utilisateur.

    Utilisé pour les endpoints nécessitant les informations de rôles.
    """
    roles: List[RoleRead] = Field(
        default_factory=list,
        description="Liste des rôles assignés à l'utilisateur"
    )

    class Config:
        from_attributes = True


class UserReadWithPermissions(UserReadWithRoles):
    """
    Schéma incluant les rôles ET les permissions calculées.

    Utilisé pour l'endpoint /me (informations de l'utilisateur connecté).
    """
    permissions: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Permissions calculées depuis tous les rôles",
        example={
            "vms": ["read", "create", "update"],
            "hypervisors": ["read"]
        }
    )

    class Config:
        from_attributes = True


class UserList(BaseModel):
    """
    Schéma pour une liste paginée d'utilisateurs.

    Utilisé pour GET /api/v1/users avec pagination.
    """
    items: List[UserRead]
    total: int
    page: int
    page_size: int
    pages: int

    class Config:
        from_attributes = True