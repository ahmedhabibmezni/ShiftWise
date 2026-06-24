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

# 5b. MigrationEvent (dépend de Migration — journal d'audit)
from app.models.migration_event import (
    MigrationEvent,
    MigrationEventType,
)

# 5c. ClusterConnectionConfig (feature 002 — connectivité cluster, indépendant)
from app.models.cluster_config import (
    ClusterConnectionConfig,
    ClusterConfigEvent,
    ClusterScopeType,
    ClusterMode,
    ClusterHealthStatus,
)

# 6. Conversion (dépend de VirtualMachine et Migration)
from app.models.conversion import (
    ConversionGroup,
    ConversionJob,
    ConversionAttempt,
    ConversionGroupStatus,
    ConversionStatus,
    SourceFormat,
    TargetFormat,
    ConversionTool,
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
    # MigrationEvent (audit log)
    "MigrationEvent",
    "MigrationEventType",
    # ClusterConnectionConfig (feature 002)
    "ClusterConnectionConfig",
    "ClusterConfigEvent",
    "ClusterScopeType",
    "ClusterMode",
    "ClusterHealthStatus",
    # Conversion
    "ConversionGroup",
    "ConversionJob",
    "ConversionAttempt",
    "ConversionGroupStatus",
    "ConversionStatus",
    "SourceFormat",
    "TargetFormat",
    "ConversionTool",
]
