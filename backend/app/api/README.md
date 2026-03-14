# 🌐 API Layer (`api/`)

The API layer is the HTTP interface of ShiftWise. It consists of route handlers organized into versioned modules and a shared dependency injection system.

---

## 📁 Structure

```
api/
├── __init__.py
├── deps.py                 # Shared dependencies (auth, DB, RBAC)
└── v1/                     # API version 1
    ├── __init__.py
    ├── auth.py             # Authentication endpoints
    ├── users.py            # User management endpoints
    ├── roles.py            # Role management endpoints
    ├── vms.py              # Virtual machine endpoints
    ├── hypervisors.py      # Hypervisor connection endpoints
    ├── migrations.py       # Migration lifecycle endpoints
    └── kubevirt.py         # KubeVirt/OpenShift operations
```

---

## 🔌 Dependency Injection (`deps.py`)

The `deps.py` module provides FastAPI dependency functions used across all routers:

| Dependency | Purpose |
|------------|---------|
| `get_db()` | Yields a SQLAlchemy database session, auto-closes after request |
| `get_current_user()` | Extracts and validates the JWT token, returns the authenticated `User` |
| `get_current_active_user()` | Extends `get_current_user` — also verifies the user is active |
| `require_role(roles)` | RBAC enforcement — checks user has one of the required roles |
| `require_permission(resource, action)` | Granular permission check against the user's role permission matrix |

### Usage in Routers

```python
from app.api.deps import get_db, get_current_active_user, require_role

@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(["super_admin", "admin"]))
):
    ...
```

---

## 📡 API v1 Routers

### `auth.py` — Authentication

Handles login, token refresh, and current user retrieval.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/auth/login` | POST | ❌ | Authenticate with email/password, returns JWT pair |
| `/auth/refresh` | POST | 🔑 | Exchange refresh token for new access token |
| `/auth/me` | GET | 🔑 | Get current authenticated user profile |

### `users.py` — User Management

Full CRUD for user accounts with multi-tenancy isolation.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/users` | GET | `admin` | List all users (tenant-scoped) |
| `/users` | POST | `admin` | Create a new user |
| `/users/{id}` | GET | `admin` | Get user by UUID |
| `/users/{id}` | PUT | `admin` | Update user data |
| `/users/{id}` | DELETE | `super_admin` | Delete user |

### `roles.py` — Role Management

Manage system and custom RBAC roles.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/roles` | GET | `admin` | List all roles |
| `/roles` | POST | `super_admin` | Create custom role |
| `/roles/{id}` | GET | `admin` | Get role details + permissions |
| `/roles/{id}` | PUT | `super_admin` | Update role permissions |
| `/roles/{id}` | DELETE | `super_admin` | Delete custom role (not system roles) |

### `vms.py` — Virtual Machines

VM inventory management with compatibility tracking.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/vms` | GET | `viewer` | List VMs (filtered by tenant) |
| `/vms` | POST | `user` | Register a VM |
| `/vms/{id}` | GET | `viewer` | Get VM details |
| `/vms/{id}` | PUT | `user` | Update VM record |
| `/vms/{id}` | DELETE | `admin` | Remove VM |

### `hypervisors.py` — Hypervisor Connections

Manage connections to VMware vSphere, libvirt/KVM, and Hyper-V sources.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/hypervisors` | GET | `admin` | List connected hypervisors |
| `/hypervisors` | POST | `admin` | Register a new hypervisor |
| `/hypervisors/{id}` | GET | `admin` | Get hypervisor details |
| `/hypervisors/{id}` | PUT | `admin` | Update connection settings |
| `/hypervisors/{id}` | DELETE | `admin` | Remove hypervisor |

### `migrations.py` — Migration Lifecycle

Manage migration requests, strategy selection, and status tracking.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/migrations` | GET | `viewer` | List migrations |
| `/migrations` | POST | `user` | Create a new migration request |
| `/migrations/{id}` | GET | `viewer` | Get migration details + status |
| `/migrations/{id}` | PUT | `user` | Update migration |
| `/migrations/{id}` | DELETE | `admin` | Cancel/remove migration |

### `kubevirt.py` — KubeVirt / OpenShift

Direct operations against the OpenShift cluster via KubeVirt APIs.

| Endpoint | Method | Min Role | Description |
|----------|--------|----------|-------------|
| `/kubevirt/namespaces` | GET | `admin` | List Kubernetes namespaces |
| `/kubevirt/vms` | GET | `admin` | List KubeVirt VMs in cluster |
| `/kubevirt/vms/{name}` | GET | `admin` | Get a specific KubeVirt VM |
| `/kubevirt/vms` | POST | `admin` | Create a VM on the cluster |
| `/kubevirt/vms/{name}` | DELETE | `admin` | Delete a KubeVirt VM |

---

## 🔐 RBAC Enforcement Flow

```
HTTP Request
    │
    ▼
FastAPI Router
    │
    ├─ Depends(get_db)                    ← DB Session
    ├─ Depends(get_current_active_user)   ← JWT Validation + Active Check
    └─ Depends(require_role([...]))       ← Role Verification
         │
         ├── Extract role from user
         ├── Check role.permissions[resource]
         └── Verify action in allowed actions
              │
              ├── ✅ Allowed → Route handler executes
              └── ❌ Denied  → 403 Forbidden

