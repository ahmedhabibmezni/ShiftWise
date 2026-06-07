# 📋 Pydantic Schemas (`schemas/`)

Pydantic **v2** models defining request/response data contracts for the ShiftWise API. Schemas handle input validation, serialization, and type coercion.

---

## 📁 Files

| File | Description |
|------|-------------|
| `auth.py` | Login, token, password-reset, and change-password schemas |
| `user.py` | User create / update / read schemas |
| `role.py` | Role create / update / read schemas |
| `hypervisor.py` | Hypervisor create / update / response schemas |
| `vm.py` | VirtualMachine create / update / response schemas |
| `migration.py` | Migration create / update / response + progress schemas |
| `conversion.py` | Disk conversion request / response schemas |
| `kubevirt.py` | Direct KubeVirt VM-creation schema |
| `cluster_config.py` | Per-tenant cluster connection config — upsert / secret-free read / scope-list / connection-test schemas (feature 002) |

---

## 🏗 Schema Pattern

Each resource follows a consistent pattern. Read schemas backed by ORM models enable `from_attributes`:

```python
from pydantic import BaseModel, ConfigDict

# Base fields shared across operations
class ResourceBase(BaseModel):
    name: str
    ...

# Create request — fields required for creation
class ResourceCreate(ResourceBase):
    ...

# Update request — all fields optional
class ResourceUpdate(BaseModel):
    name: str | None = None
    ...

# Read/response — includes id and timestamps, mapped from the ORM object
class ResourceResponse(ResourceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

> Schemas use **Pydantic v2** — `model_config = ConfigDict(from_attributes=True)` and `@field_validator`, never the v1 `class Config`. Primary keys are `int`. Pagination wrappers (`*ListResponse` / `UserList`) are composed manually and do not set `from_attributes`.

---

## 📄 Schema Details

### `auth.py`

| Schema | Purpose |
|--------|---------|
| `LoginRequest` | Email + password for `POST /auth/login` |
| `TokenResponse` | Access token + token type — the refresh token is set as an `HttpOnly` cookie, **not** returned in the body |
| `ChangePasswordRequest` | Old + new password |
| `ResetPasswordRequest` / `ResetPasswordConfirm` | Password-reset flow |
| `VerifyEmailRequest` | Email-verification request |
| `MessageResponse` | Generic `{message, success}` confirmation |
| `TokenPayload` | Internal JWT payload (`sub`, `exp`, `type`, optional `fam`, `jti`) |

### `user.py`

| Schema | Fields / Role |
|--------|---------------|
| `UserBase` | Shared: `email`, `username`, `first_name`, `last_name`, `tenant_id`, `is_active` |
| `UserCreate` | `UserBase` + `password`, `role_ids: list[int]` |
| `UserUpdate` | All fields optional |
| `UserInDB` | `UserBase` + `id`, `hashed_password`, status flags, timestamps |
| `UserRead` | API response without password; includes `last_login_at`, `last_login_ip` |
| `UserReadWithRoles` | `UserRead` + `roles: list[RoleRead]` |
| `UserReadWithPermissions` | `UserReadWithRoles` + computed `permissions` (used by `/auth/me`) |
| `UserList` | Paginated `items` + `total` / `page` / `page_size` / `pages` |

### `role.py`

| Schema | Fields / Role |
|--------|---------------|
| `RoleBase` | Shared: `name`, `description`, `permissions`, `is_active` |
| `RoleCreate` | `RoleBase` (no additional fields) |
| `RoleUpdate` | All fields optional |
| `RoleInDB` | `RoleBase` + `id`, `is_system_role`, timestamps |
| `RoleRead` | Primary API response schema |
| `RoleWithUsers` | `RoleRead` + `user_count` |

### `hypervisor.py`

| Schema | Fields / Role |
|--------|---------------|
| `HypervisorBase` | `name`, `description`, `type`, `host`, `port` |
| `HypervisorCreate` | `HypervisorBase` + `username`, `password`, `verify_ssl`, `ssl_cert_path`, `connection_config`, `tags` |
| `HypervisorUpdate` | All fields optional |
| `HypervisorResponse` | Full read response (+ computed `is_reachable`, `connection_url`, `needs_sync`) |
| `HypervisorListResponse` | Paginated list wrapper |
| `HypervisorTestConnection` / `HypervisorTestConnectionResponse` | Ad-hoc connection test |

### `vm.py`

| Schema | Fields / Role |
|--------|---------------|
| `VMBase` | `name`, `description`, `cpu_cores`, `memory_mb`, `disk_gb`, `os_type`, `os_version`, `os_name` |
| `VMCreate` | `VMBase` + source fields, network fields, `tags` |
| `VMUpdate` | All fields optional (`status` / `compatibility_status` excluded from input) |
| `VMResponse` | Full read response (+ computed `is_compatible`, `is_migrated`, `can_migrate`) |
| `VMListResponse` | Paginated list wrapper |

### `migration.py`

| Schema | Fields / Role |
|--------|---------------|
| `MigrationBase` | `strategy`, `target_storage_class` |
| `MigrationCreate` | `MigrationBase` + `vm_id`, `scheduled_at`, `migration_config`, `notes`, `tags` |
| `MigrationUpdate` | All fields optional (`target_namespace` is immutable) |
| `MigrationProgressUpdate` | Worker progress report |
| `MigrationCancel` / `MigrationRollback` | Action schemas with an optional `reason` |
| `MigrationResponse` | Full read response (+ computed `is_active`, `is_completed`, durations) |
| `MigrationListResponse` | Paginated list wrapper |
| `MigrationStats` | Aggregate migration statistics |

### `conversion.py`

| Schema | Fields / Role |
|--------|---------------|
| `ConversionCreate` | `vm_id`, `target_format`, `cold`, `max_attempts`, `pull_options`, `migration_id` |
| `ConversionAttemptResponse` | Single conversion-attempt audit row |
| `ConversionJobResponse` | Conversion job (+ computed `is_terminal`, `can_retry`) |
| `ConversionGroupResponse` | Conversion group with embedded `jobs` |
| `ConversionGroupListResponse` | Paginated list wrapper |
| `ConversionCancel` / `ConversionRetry` | Action schemas |
| `ConversionStats` | Aggregate conversion statistics |

### `kubevirt.py`

| Schema | Fields / Role |
|--------|---------------|
| `KubeVirtVMCreate` | Direct KubeVirt VM creation: `name`, `cpu`, `memory`, `image`, `disk_size`, `storage_class`, `run_strategy` |

---

## 🔒 Validation

Schemas enforce:
- **Email format** via `pydantic[email]` (`EmailStr`)
- **Password strength** — min 8 chars, upper + lower case, digit, special character
- **Username / tenant-id format** — slug-style rules via `@field_validator`
- **Enum constraints** for status, type, and strategy fields
- **Required vs optional** field distinction between create and update operations
