# 🗃 Database Models (`models/`)

SQLAlchemy ORM models representing the ShiftWise data layer. All models inherit from a common `BaseModel` that provides an integer auto-increment primary key and timezone-aware audit timestamps.

---

## 📁 Files

| File | Model(s) | Description |
|------|----------|-------------|
| `base.py` | `BaseModel`, `Base` | Abstract base model + SQLAlchemy declarative `Base` |
| `user.py` | `User`, `user_roles` | User accounts with multi-tenancy |
| `role.py` | `Role`, `ROLE_PERMISSIONS` | RBAC roles and the system-role permission matrix |
| `hypervisor.py` | `Hypervisor`, `HypervisorType`, `HypervisorStatus` | Source hypervisor connections |
| `virtual_machine.py` | `VirtualMachine`, `VMStatus`, `CompatibilityStatus`, `OSType` | VM inventory records |
| `migration.py` | `Migration`, `MigrationStatus`, `MigrationStrategy` | Migration lifecycle tracking |
| `conversion.py` | `ConversionGroup`, `ConversionJob`, `ConversionAttempt` + status/format enums | Disk conversion tracking |

---

## 🧱 `BaseModel` — Abstract Base

All models inherit from `BaseModel`, which provides:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `Integer` | Auto-increment primary key |
| `created_at` | `DateTime(timezone=True)` | Record creation timestamp (UTC) |
| `updated_at` | `DateTime(timezone=True)` | Last update timestamp (UTC, auto-updated) |

> **Primary keys are integer auto-increment — not UUID.**

---

## 👤 `User`

| Field | Type | Description |
|-------|------|-------------|
| `email` | `String(255)` | Unique email address (login identifier) |
| `username` | `String(100)` | Unique username |
| `first_name` | `String(100)` | Given name (nullable) |
| `last_name` | `String(100)` | Family name (nullable) |
| `hashed_password` | `String(255)` | bcrypt password hash |
| `tenant_id` | `String(100)` | Organization/tenant identifier |
| `is_active` | `Boolean` | Account active status |
| `is_verified` | `Boolean` | Email verified flag |
| `is_superuser` | `Boolean` | Super-admin flag (bypasses RBAC) |
| `last_login_at` | `DateTime(timezone=True)` | Last successful login (audit) |
| `last_login_ip` | `String(45)` | Source IP of the last login (audit) |
| `roles` | M2M → `Role` | Assigned roles via the `user_roles` join table |

`full_name` is a **computed property** (`first_name` + `last_name`, falling back to `username`) — not a column. Helper methods: `has_role()`, `has_permission()`, `get_all_permissions()`, `can_access_tenant()`.

### Multi-Tenancy

The `tenant_id` field isolates data between organizations. Every non-superuser query is scoped to the caller's `tenant_id`.

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
        "users": ["*"], "roles": ["*"], "hypervisors": ["*"], "vms": ["*"],
        "migrations": ["*"], "conversions": ["*"], "reports": ["*"], "settings": ["*"],
    },
    "admin": {
        "users": ["read", "create", "update"], "roles": ["read"],
        "hypervisors": ["*"], "vms": ["*"], "migrations": ["*"],
        "conversions": ["*"], "reports": ["*"],
    },
    "user": {
        "vms": ["read", "create", "update"],
        "migrations": ["read", "create"],
        "conversions": ["read", "create"], "reports": ["read"],
    },
    "viewer": {
        "vms": ["read"], "migrations": ["read"],
        "conversions": ["read"], "reports": ["read"],
    },
}
```

---

## 🖥 `Hypervisor`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `String(255)` | Display name (unique) |
| `description` | `Text` | Description |
| `type` | `HypervisorType` | Hypervisor type (enum) |
| `host` | `String(255)` | Connection hostname/IP |
| `port` | `Integer` | Connection port (nullable) |
| `username` | `String(255)` | Auth username |
| `password` | `Text` | Auth password |
| `verify_ssl` | `Boolean` | Verify SSL certificates |
| `status` | `HypervisorStatus` | Connection status (enum) |
| `is_active` | `Boolean` | Whether the hypervisor is enabled |
| `last_sync_at` | `DateTime(timezone=True)` | Last VM synchronization |
| `tenant_id` | `String(100)` | Owning tenant |

> ⚠️ Hypervisor credentials (`password`) are currently stored **in plaintext** — a known limitation. Encryption via Fernet or Vault is planned.

---

## 💻 `VirtualMachine`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `String(255)` | VM display name |
| `source_hypervisor_id` | `Integer` → Hypervisor | Source hypervisor FK (nullable, `SET NULL`) |
| `source_uuid` | `String(255)` | VM UUID on the source hypervisor |
| `cpu_cores` | `Integer` | Virtual CPU count |
| `memory_mb` | `Integer` | Memory in MB |
| `disk_gb` | `Integer` | Total disk size in GB |
| `os_type` | `OSType` | OS family (enum) |
| `os_name` / `os_version` | `String(255)` | OS name and version |
| `ip_address` | `String(45)` | IPv4/IPv6 address |
| `status` | `VMStatus` | Migration-lifecycle status (enum) |
| `compatibility_status` | `CompatibilityStatus` | Compatibility status (enum) |
| `compatibility_details` | `JSON` | Analyzer output details |
| `tenant_id` | `String(100)` | Owning tenant |

Properties: `is_compatible`, `is_migrated`, `can_migrate`.

---

## 🔄 `Migration`

| Field | Type | Description |
|-------|------|-------------|
| `vm_id` | `Integer` → VirtualMachine | Source VM FK (`CASCADE`) |
| `status` | `MigrationStatus` | Lifecycle status (enum) |
| `strategy` | `MigrationStrategy` | Migration strategy (enum) |
| `progress_percentage` | `Float` | Progress 0–100 |
| `current_step` | `String(255)` | Current pipeline step |
| `started_at` | `DateTime(timezone=True)` | Migration start time |
| `completed_at` | `DateTime(timezone=True)` | Migration completion time |
| `success` | `Boolean` | Outcome (`None` while running) |
| `error_message` | `Text` | Failure details (if any) |
| `target_namespace` | `String(255)` | OpenShift target namespace |
| `can_rollback` | `Boolean` | Whether rollback is possible |
| `tenant_id` | `String(100)` | Owning tenant |

Properties: `is_active`, `is_completed`, `duration_seconds`, `estimated_time_remaining_seconds`.

---

## 🔢 Enumerations

All enums are string enums (`str, enum.Enum`). Exact members:

| Enum | Values |
|------|--------|
| `HypervisorType` | `VSPHERE`, `VMWARE_WORKSTATION`, `VMWARE_ESXi`, `HYPER_V`, `KVM`, `PROXMOX`, `OVIRT`, `VIRTUALBOX`, `XEN`, `OTHER` |
| `HypervisorStatus` | `ACTIVE`, `INACTIVE`, `ERROR`, `UNREACHABLE`, `AUTHENTICATING`, `DISCOVERING`, `UNKNOWN` |
| `VMStatus` | `DISCOVERED`, `ANALYZING`, `COMPATIBLE`, `INCOMPATIBLE`, `PARTIAL`, `MIGRATING`, `MIGRATED`, `FAILED`, `ARCHIVED` |
| `CompatibilityStatus` | `COMPATIBLE`, `PARTIAL`, `INCOMPATIBLE`, `UNKNOWN` |
| `OSType` | `WINDOWS`, `LINUX`, `OTHER`, `UNKNOWN` |
| `MigrationStatus` | `PENDING`, `VALIDATING`, `PREPARING`, `TRANSFERRING`, `CONFIGURING`, `STARTING`, `VERIFYING`, `COMPLETED`, `FAILED`, `CANCELLED`, `ROLLBACK`, `ROLLED_BACK` |
| `MigrationStrategy` | `DIRECT`, `CONVERSION`, `HYBRID`, `COLD`, `WARM`, `AUTO` |

---

## 🔗 Relationships (Entity Diagram)

```
┌──────────┐   M:N (user_roles)   ┌──────────┐
│   User   │◄────────────────────▶│   Role   │
└──────────┘                       └──────────┘

┌──────────────┐  1:N   ┌──────────────────┐  1:N   ┌─────────────┐
│  Hypervisor  │───────▶│  VirtualMachine   │───────▶│  Migration  │
└──────────────┘        └──────────────────┘        └─────────────┘
                                 │ 1:N
                                 ▼
                        ┌────────────────────┐
                        │   ConversionGroup   │
                        └────────────────────┘
```

---

## ⚠️ Import Order

Models are imported in dependency order (enforced in `__init__.py`):

1. `Base`, `BaseModel` — no dependencies
2. `Role`, `User` (+ `user_roles`) — user depends on role via M2M
3. `Hypervisor` — independent
4. `VirtualMachine` — depends on `Hypervisor` (FK)
5. `Migration` — depends on `VirtualMachine` (FK)
6. `Conversion*` — depends on `VirtualMachine` and `Migration`
