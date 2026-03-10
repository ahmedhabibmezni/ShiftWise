"""
ShiftWise Models Package

Importe tous les modèles dans le bon ordre pour SQLAlchemy.
L'ordre est critique pour les relations entre modèles.
"""

# 1. Base (doit être en premier)
from app.models.base import BaseModel, Base

# 2. Modèles sans dépendances (User, Role)
from app.models.role import Role, ROLE_PERMISSIONS
from app.models.user import User, user_roles

# 3. Hypervisor (référencé par VirtualMachine)
from app.models.hypervisor import (
    Hypervisor,
    HypervisorType,
    HypervisorStatus
)

# 4. VirtualMachine (référencé par Migration, dépend de Hypervisor)
from app.models.virtual_machine import (
    VirtualMachine,
    VMStatus,
    CompatibilityStatus,
    OSType
)

# 5. Migration (dépend de VirtualMachine)
from app.models.migration import (
    Migration,
    MigrationStatus,
    MigrationStrategy
)

# Export explicite
__all__ = [
    # Base
    "Base",
    "BaseModel",
    # User & Role
    "User",
    "user_roles",
    "Role",
    "ROLE_PERMISSIONS",
    # Hypervisor
    "Hypervisor",
    "HypervisorType",
    "HypervisorStatus",
    # VirtualMachine
    "VirtualMachine",
    "VMStatus",
    "CompatibilityStatus",
    "OSType",
    # Migration
    "Migration",
    "MigrationStatus",
    "MigrationStrategy",
]