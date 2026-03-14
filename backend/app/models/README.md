# 🗃 Database Models (`models/`)

SQLAlchemy ORM models representing the ShiftWise data layer. All models inherit from a common `BaseModel` that provides UUID primary keys, audit timestamps, and tenant awareness.

---

## 📁 Files

| File | Model(s) | Description |
|------|----------|-------------|
| `base.py` | `BaseModel`, `Base` | Abstract base model with shared fields |
| `user.py` | `User`, `user_roles` | User accounts with multi-tenancy |
| `role.py` | `Role`, `ROLE_PERMISSIONS` | RBAC roles and permission definitions |
| `hypervisor.py` | `Hypervisor`, `HypervisorType`, `HypervisorStatus` | Source hypervisor connections |
| `virtual_machine.py` | `VirtualMachine`, `VMStatus`, `CompatibilityStatus`, `OSType` | VM inventory records |
| `migration.py` | `Migration`, `MigrationStatus`, `MigrationStrategy` | Migration lifecycle tracking |

---

## 🧱 `BaseModel` — Abstract Base

All models inherit from `BaseModel`, which provides:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Primary key (auto-generated) |
| `created_at` | `DateTime` | Record creation timestamp (UTC) |
| `updated_at` | `DateTime` | Last update timestamp (UTC, auto-updated) |

---

## 👤 `User`

| Field | Type | Description |
|-------|------|-------------|
| `email` | `String(255)` | Unique email address |
| `hashed_password` | `String` | bcrypt password hash |
| `full_name` | `String(255)` | Display name |
| `tenant_id` | `String(100)` | Organization/tenant identifier |
| `is_active` | `Boolean` | Account active status |
| `is_superuser` | `Boolean` | Super admin flag |
| `roles` | M2M → `Role` | Assigned roles (via `user_roles` join table) |

### Multi-Tenancy

The `tenant_id` field isolates data between organizations. All CRUD queries filter by the current user's `tenant_id` to prevent cross-tenant data access.

---

## 🛡 `Role`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `String(50)` | Unique role identifier |
| `description` | `Text` | Human-readable description |
| `permissions` | `JSON` | Permission matrix (`{resource: [actions]}`) |
| `is_system_role` | `Boolean` | `True` for built-in roles (non-deletable) |
| `is_active` | `Boolean` | Whether the role can be assigned |

### Permission Matrix (`ROLE_PERMISSIONS`)

```python
ROLE_PERMISSIONS = {
    "super_admin": {
        "users": ["*"], "roles": ["*"], "hypervisors": ["*"],
        "vms": ["*"], "migrations": ["*"], "reports": ["*"], "settings": ["*"]
    },
    "admin": {
        "users": ["read", "create", "update"], "roles": ["read"],
        "hypervisors": ["*"], "vms": ["*"], "migrations": ["*"], "reports": ["*"]
    },
    "user": {
        "vms": ["read", "create", "update"],
        "migrations": ["read", "create"], "reports": ["read"]
    },
    "viewer": {
        "vms": ["read"], "migrations": ["read"], "reports": ["read"]
    }
}
```

---

## 🖥 `Hypervisor`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `String` | Display name |
| `type` | `HypervisorType` | `vmware`, `libvirt`, `hyperv` |
| `host` | `String` | Connection hostname/IP |
| `port` | `Integer` | Connection port |
| `username` | `String` | Auth username |
| `password` | `String` | Auth password (encrypted) |
| `status` | `HypervisorStatus` | `connected`, `disconnected`, `error` |
| `tenant_id` | `String` | Owning tenant |

---

## 💻 `VirtualMachine`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `String` | VM display name |
| `hypervisor_id` | `UUID` → Hypervisor | Source hypervisor FK |
| `vcpus` | `Integer` | Virtual CPU count |
| `memory_mb` | `Integer` | Memory in MB |
| `disk_size_gb` | `Float` | Total disk size in GB |
| `os_type` | `OSType` | `linux`, `windows`, `other` |
| `status` | `VMStatus` | `running`, `stopped`, `migrating`, etc. |
| `compatibility_status` | `CompatibilityStatus` | `compatible`, `partially_compatible`, `incompatible` |
| `tenant_id` | `String` | Owning tenant |

---

## 🔄 `Migration`

| Field | Type | Description |
|-------|------|-------------|
| `vm_id` | `UUID` → VirtualMachine | Source VM FK |
| `strategy` | `MigrationStrategy` | `direct`, `conversion`, `alternative` |
| `status` | `MigrationStatus` | `pending`, `in_progress`, `completed`, `failed`, `cancelled` |
| `started_at` | `DateTime` | Migration start time |
| `completed_at` | `DateTime` | Migration completion time |
| `error_message` | `Text` | Failure details (if any) |
| `tenant_id` | `String` | Owning tenant |

---

## 🔗 Relationships (Entity Diagram)

```
┌──────────┐     M:N      ┌──────────┐
│   User   │◄────────────►│   Role   │
└────┬─────┘  user_roles   └──────────┘
     │
     │ tenant_id
     │
┌────▼───────────┐  1:N   ┌──────────────────┐  1:N   ┌───────────┐
│   Hypervisor   │◄───────│  VirtualMachine   │◄───────│ Migration │
└────────────────┘        └──────────────────┘        └───────────┘
```

---

## ⚠️ Import Order

Models must be imported in dependency order (enforced in `__init__.py`):

1. `Base`, `BaseModel` — no dependencies
2. `Role`, `User` — user depends on role via M2M
3. `Hypervisor` — independent
4. `VirtualMachine` — depends on Hypervisor (FK)
5. `Migration` — depends on VirtualMachine (FK)