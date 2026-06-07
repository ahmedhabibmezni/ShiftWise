# 🌐 API Layer (`api/`)

The API layer is the HTTP interface of ShiftWise: versioned route handlers plus a shared dependency-injection module that enforces authentication, RBAC, and multi-tenancy.

---

## 📁 Structure

```
api/
├── __init__.py
├── deps.py                 # Shared dependencies (auth, RBAC, tenant scoping)
└── v1/                     # API version 1
    ├── __init__.py
    ├── auth.py             # Authentication endpoints
    ├── users.py            # User management endpoints
    ├── roles.py            # Role management endpoints
    ├── vms.py              # VM inventory, analysis, conversion trigger
    ├── hypervisors.py      # Hypervisor connection + sync endpoints
    ├── migrations.py       # Migration lifecycle endpoints
    ├── kubevirt.py         # KubeVirt / OpenShift operations
    ├── conversions.py      # Disk conversion tracking
    └── infrastructure.py   # Per-tenant cluster connection config
```

---

## 🔌 Dependency Injection (`deps.py`)

`deps.py` provides the FastAPI dependencies used across all routers:

| Dependency | Purpose |
|------------|---------|
| `get_db()` | Yields a SQLAlchemy session, closed after the request (re-exported from `core.database`) |
| `get_current_user()` | Decodes and validates the JWT access token, returns the authenticated `User` |
| `get_current_active_user()` | `get_current_user` plus an active-account check (compatibility alias) |
| `get_current_superuser()` | Requires `is_superuser`, raises `403` otherwise |
| `check_permission(resource, action)` | **Factory** — returns a dependency that enforces a single RBAC permission |
| `get_current_user_tenant()` | Returns the caller's `tenant_id` |
| `validate_kubevirt_namespace()` | Resolves and validates a namespace to `shiftwise-{tenant_id}` for non-superusers |
| `PermissionChecker` | Class — checks an *any-of* list of `(resource, action)` permission pairs |

`check_permission` is the primary RBAC gate. **Superusers bypass all permission checks.**

### Usage in Routers

```python
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, check_permission
from app.models import User


@router.get("/")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission("users", "read"))],
):
    ...
```

Dependencies use the `Annotated[Type, Depends(...)]` syntax (SonarQube rule S8410).

---

## 📡 API v1 Routers

Nine routers, all mounted under `/api/v1`:

| Router | Prefix | Responsibility |
|--------|--------|----------------|
| `auth` | `/api/v1/auth` | Login, refresh, logout, change-password, current user |
| `users` | `/api/v1/users` | User CRUD and role assignment (tenant-scoped) |
| `roles` | `/api/v1/roles` | System and custom RBAC role management |
| `vms` | `/api/v1/vms` | VM inventory, compatibility analysis, conversion trigger |
| `hypervisors` | `/api/v1/hypervisors` | Hypervisor connections, test-connection, sync |
| `migrations` | `/api/v1/migrations` | Migration lifecycle (create, start, cancel) |
| `kubevirt` | `/api/v1/kubevirt` | Direct KubeVirt / OpenShift cluster operations |
| `conversions` | `/api/v1/conversions` | Disk conversion job tracking |
| `infrastructure` | `/api/v1/infrastructure` | Per-tenant cluster connection config (mode, kubeconfig upload, live test) |

The full endpoint inventory is in [`../../README.md`](../../README.md); request/response detail is in [`../../../docs/api-reference.md`](../../../docs/api-reference.md).

---

## 🧭 Route Ordering Rule

**Static routes must be declared before dynamic `/{id}` routes** in every router file — otherwise the static segment is parsed as an `int` ID parameter and the request returns `422`.

For example, in `roles.py`: `/count`, `/name/{role_name}`, `/init-system-roles`, and `/permissions/resources` are all declared **before** `/{role_id}`.

---

## 🔐 RBAC Enforcement Flow

```
HTTP Request
    │
    ▼
FastAPI Router
    │
    ├─ Depends(get_db)                              ← DB session
    └─ Depends(check_permission(resource, action))
         │
         ├─ get_current_user()  → decode JWT, load the User
         ├─ is_superuser?  ─────────────────────────▶ ✅ Allowed
         └─ User.has_permission(resource, action)
              evaluated over the user's active roles
              │
              ├─ ✅ Allowed → route handler executes
              └─ ❌ Denied  → 403 Forbidden
```
