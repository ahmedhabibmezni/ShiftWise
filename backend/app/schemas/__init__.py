"""
Schémas Pydantic pour l'API REST

Expose tous les schémas pour faciliter les imports.
"""

# User & Auth schemas (existants) - utiliser les vrais noms
try:
    from app.schemas.user import (
        UserCreate,
        UserUpdate,
        UserRead,
        UserReadWithRoles,
        UserReadWithPermissions,
        UserList
    )
except ImportError:
    pass

try:
    from app.schemas.role import RoleRead
except ImportError:
    pass

try:
    from app.schemas.auth import (
        TokenResponse,
        LoginRequest
    )
except ImportError:
    pass

# VM schemas (nouveaux)
from app.schemas.vm import (
    VMCreate,
    VMUpdate,
    VMResponse,
    VMListResponse,
    VMStatusEnum,
    CompatibilityStatusEnum,
    OSTypeEnum
)

# Hypervisor schemas (nouveaux)
from app.schemas.hypervisor import (
    HypervisorCreate,
    HypervisorUpdate,
    HypervisorResponse,
    HypervisorListResponse,
    HypervisorTestConnection,
    HypervisorTestConnectionResponse,
    HypervisorTypeEnum,
    HypervisorStatusEnum
)

# Migration schemas (nouveaux)
from app.schemas.migration import (
    MigrationCreate,
    MigrationUpdate,
    MigrationProgressUpdate,
    MigrationResponse,
    MigrationListResponse,
    MigrationStart,
    MigrationCancel,
    MigrationRollback,
    MigrationStats,
    MigrationStatusEnum,
    MigrationStrategyEnum
)

__all__ = [
    # VM
    "VMCreate",
    "VMUpdate",
    "VMResponse",
    "VMListResponse",
    "VMStatusEnum",
    "CompatibilityStatusEnum",
    "OSTypeEnum",
    # Hypervisor
    "HypervisorCreate",
    "HypervisorUpdate",
    "HypervisorResponse",
    "HypervisorListResponse",
    "HypervisorTestConnection",
    "HypervisorTestConnectionResponse",
    "HypervisorTypeEnum",
    "HypervisorStatusEnum",
    # Migration
    "MigrationCreate",
    "MigrationUpdate",
    "MigrationProgressUpdate",
    "MigrationResponse",
    "MigrationListResponse",
    "MigrationStart",
    "MigrationCancel",
    "MigrationRollback",
    "MigrationStats",
    "MigrationStatusEnum",
    "MigrationStrategyEnum",
]