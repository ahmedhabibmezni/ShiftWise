"""
ShiftWise Role Model

Gère les rôles et permissions dans le système RBAC.

Rôles prédéfinis :
- SUPER_ADMIN : Accès complet au système
- ADMIN : Gestion complète des ressources de son tenant
- USER : Accès lecture/écriture aux ressources assignées
- VIEWER : Accès lecture seule
"""

from sqlalchemy import Column, String, Boolean, JSON, Text, text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Role(BaseModel):
    """
    Modèle pour les rôles utilisateur (RBAC).

    Chaque rôle définit un ensemble de permissions.
    Les utilisateurs sont assignés à un ou plusieurs rôles.

    Attributes:
        name: Nom unique du rôle (ex: "admin", "user", "viewer")
        description: Description du rôle
        permissions: Dictionnaire JSON des permissions
        is_system_role: True si rôle système (non modifiable)
        is_active: True si le rôle est actif
    """

    __tablename__ = "roles"

    # Nom unique du rôle
    name = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Nom unique du rôle (ex: admin, user)"
    )

    # Description du rôle
    description = Column(
        Text,
        nullable=True,
        comment="Description détaillée du rôle et ses responsabilités"
    )

    # Permissions au format JSON
    # Structure: {"resource": ["action1", "action2"]}
    # Ex: {"vms": ["read", "create", "update", "delete"], "hypervisors": ["read"]}
    permissions = Column(
        JSON,
        nullable=False,
        default=dict,
        comment="Permissions du rôle au format JSON"
    )

    # Rôle système (non modifiable/supprimable)
    # Audit D16 — `server_default` cross-dialect en complément du `default`
    # Python : un INSERT brut ne peut pas laisser ces flags NULL.
    is_system_role = Column(
        Boolean,
        default=False,
        server_default=text("0"),
        nullable=False,
        comment="True si rôle système prédéfini (non modifiable)"
    )

    # Statut actif/inactif
    is_active = Column(
        Boolean,
        default=True,
        server_default=text("1"),
        nullable=False,
        comment="True si le rôle est actif et peut être assigné"
    )

    # Relations
    # users : Liste des utilisateurs ayant ce rôle (défini dans User model)

    def __repr__(self) -> str:
        return f"<Role(name={self.name}, active={self.is_active})>"

    def has_permission(self, resource: str, action: str) -> bool:
        """
        Vérifie si le rôle a une permission spécifique.

        Args:
            resource: Nom de la ressource (ex: "vms", "hypervisors")
            action: Action demandée (ex: "read", "create", "update", "delete")

        Returns:
            bool: True si la permission existe, False sinon

        Example:
            >>> role.has_permission("vms", "delete")
            True
        """
        if not self.permissions:
            return False

        resource_permissions = self.permissions.get(resource, [])
        return action in resource_permissions or "*" in resource_permissions


# Permissions prédéfinies pour les rôles système
ROLE_PERMISSIONS = {
    "super_admin": {
        # Accès complet à tout
        "users": ["*"],
        "roles": ["*"],
        "hypervisors": ["*"],
        "vms": ["*"],
        "migrations": ["*"],
        "conversions": ["*"],
        "reports": ["*"],
        "settings": ["*"],
        # Feature 002 — connectivité cluster (le superuser bypasse de toute
        # façon ; listé pour cohérence et pour un super_admin non-superuser).
        "infrastructure": ["*"],
    },
    "admin": {
        # Gestion complète de son tenant
        "users": ["read", "create", "update"],
        "roles": ["read"],
        "hypervisors": ["*"],
        "vms": ["*"],
        "migrations": ["*"],
        "conversions": ["*"],
        "reports": ["*"],
        # Feature 002 — un tenant admin gère la connectivité de SON tenant
        # (le scoping tenant est appliqué dans le handler).
        "infrastructure": ["read", "update"],
    },
    "user": {
        # Accès aux ressources assignées
        # Audit B19 — un `user` peut créer une VM/migration ; il doit donc
        # pouvoir lire les hyperviseurs (source obligatoire d'une migration).
        "hypervisors": ["read"],
        "vms": ["read", "create", "update"],
        "migrations": ["read", "create"],
        "conversions": ["read", "create"],
        "reports": ["read"],
    },
    "viewer": {
        # Lecture seule — Audit B20 : le rôle "read-only" doit voir
        # l'ensemble des ressources, pas seulement vms/migrations.
        # Aucune action d'écriture ici, par définition du rôle.
        "users": ["read"],
        "roles": ["read"],
        "hypervisors": ["read"],
        "vms": ["read"],
        "migrations": ["read"],
        "conversions": ["read"],
        "reports": ["read"],
    },
}
