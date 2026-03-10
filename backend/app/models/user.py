"""
ShiftWise User Model

Gère les utilisateurs avec support multi-tenancy.

Chaque utilisateur :
- Appartient à un tenant (organisation)
- A un ou plusieurs rôles
- Peut avoir accès à des VMs spécifiques
- Peut partager des VMs avec d'autres utilisateurs
"""

from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, Table
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


# Table d'association Many-to-Many pour User <-> Role
user_roles = Table(
    'user_roles',
    BaseModel.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    comment="Association entre utilisateurs et rôles"
)


class User(BaseModel):
    """
    Modèle pour les utilisateurs de ShiftWise.

    Support multi-tenancy : chaque utilisateur appartient à un tenant.
    Un utilisateur peut avoir plusieurs rôles.

    Attributes:
        email: Email unique de l'utilisateur (login)
        username: Nom d'utilisateur unique
        full_name: Nom complet
        hashed_password: Mot de passe hashé (bcrypt)
        tenant_id: ID du tenant (organisation)
        is_active: True si compte actif
        is_verified: True si email vérifié
        is_superuser: True si super administrateur
    """

    __tablename__ = "users"

    # Informations d'identification
    email = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Email de l'utilisateur (identifiant de connexion)"
    )

    username = Column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Nom d'utilisateur unique"
    )

    first_name = Column(
        String(100),
        nullable=True,
        comment="Prénom de l'utilisateur"
    )

    last_name = Column(
        String(100),
        nullable=True,
        comment="Nom de famille de l'utilisateur"
    )

    # Mot de passe hashé (bcrypt)
    hashed_password = Column(
        String(255),
        nullable=False,
        comment="Mot de passe hashé avec bcrypt"
    )

    # Multi-tenancy : appartenance à un tenant (organisation)
    tenant_id = Column(
        String(100),
        nullable=False,
        index=True,
        comment="ID du tenant (organisation) de l'utilisateur"
    )

    # Statuts
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="True si le compte est actif"
    )

    is_verified = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="True si l'email a été vérifié"
    )

    is_superuser = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="True si super administrateur (accès complet)"
    )

    # Relations

    # Roles : Many-to-Many avec Role
    # Charge les rôles automatiquement avec lazy="joined"
    roles = relationship(
        "Role",
        secondary=user_roles,
        backref="users",
        lazy="joined"
    )

    # VMs créées par cet utilisateur (défini dans VM model)
    # created_vms = relationship("VirtualMachine", back_populates="owner")

    # VMs partagées avec cet utilisateur (défini dans VM model via table association)
    # shared_vms = relationship("VirtualMachine", secondary="vm_user_access")

    @property
    def full_name(self) -> str:
        """
        Retourne le nom complet de l'utilisateur.

        Concatène first_name et last_name.
        Si les deux sont vides, retourne le username.

        Returns:
            str: Nom complet de l'utilisateur

        Example:
            >>> user.first_name = "Ahmed"
            >>> user.last_name = "MEZNI"
            >>> user.full_name
            "Ahmed MEZNI"
        """
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        else:
            return self.username

    def __repr__(self) -> str:
        return f"<User(email={self.email}, tenant={self.tenant_id})>"

    def has_role(self, role_name: str) -> bool:
        """
        Vérifie si l'utilisateur a un rôle spécifique.

        Args:
            role_name: Nom du rôle à vérifier

        Returns:
            bool: True si l'utilisateur a ce rôle

        Example:
            >>> user.has_role("admin")
            True
        """
        return any(role.name == role_name for role in self.roles)

    def has_permission(self, resource: str, action: str) -> bool:
        """
        Vérifie si l'utilisateur a une permission spécifique.

        Vérifie tous les rôles de l'utilisateur.
        Si superuser, a toutes les permissions.

        Args:
            resource: Nom de la ressource (ex: "vms", "hypervisors")
            action: Action demandée (ex: "read", "create", "update", "delete")

        Returns:
            bool: True si l'utilisateur a la permission

        Example:
            >>> user.has_permission("vms", "delete")
            True
        """
        # Superuser a toutes les permissions
        if self.is_superuser:
            return True

        # Vérifie dans tous les rôles
        for role in self.roles:
            if role.is_active and role.has_permission(resource, action):
                return True

        return False

    def get_all_permissions(self) -> dict:
        """
        Retourne toutes les permissions de l'utilisateur.

        Combine les permissions de tous ses rôles actifs.

        Returns:
            dict: Dictionnaire des permissions {"resource": ["action1", "action2"]}

        Example:
            >>> user.get_all_permissions()
            {"vms": ["read", "create"], "hypervisors": ["read"]}
        """
        if self.is_superuser:
            return {"*": ["*"]}

        all_permissions = {}

        for role in self.roles:
            if not role.is_active:
                continue

            for resource, actions in (role.permissions or {}).items():
                if resource not in all_permissions:
                    all_permissions[resource] = set()

                if isinstance(actions, list):
                    all_permissions[resource].update(actions)

        # Convertir les sets en listes
        return {
            resource: list(actions)
            for resource, actions in all_permissions.items()
        }

    def can_access_tenant(self, tenant_id: str) -> bool:
        """
        Vérifie si l'utilisateur peut accéder à un tenant donné.

        Args:
            tenant_id: ID du tenant à vérifier

        Returns:
            bool: True si accès autorisé
        """
        # Superuser peut accéder à tous les tenants
        if self.is_superuser:
            return True

        # Sinon, seulement son propre tenant
        return self.tenant_id == tenant_id