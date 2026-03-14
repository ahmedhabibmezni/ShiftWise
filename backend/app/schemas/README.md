# 📋 Pydantic Schemas (`schemas/`)

Pydantic models defining request/response data contracts for all ShiftWise API endpoints. Schemas handle input validation, serialization, and type coercion.

---

## 📁 Files

| File | Description |
|------|-------------|
| `auth.py` | Login request, token response, token data |
| `user.py` | User create/update/response schemas |
| `role.py` | Role create/update/response schemas |
| `hypervisor.py` | Hypervisor create/update/response schemas |
| `vm.py` | VirtualMachine create/update/response schemas |
| `migration.py` | Migration create/update/response schemas |

---

## 🏗 Schema Pattern

Each resource follows a consistent pattern:

```python
# Base fields shared across operations
class ResourceBase(BaseModel):
    name: str
    ...

# Create request — fields required for creation
class ResourceCreate(ResourceBase):
    required_field: str

# Update request — all fields optional
class ResourceUpdate(BaseModel):
    name: str | None = None
    ...

# Database response — includes id, timestamps
class ResourceResponse(ResourceBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Enable ORM mode
```

---

## 📄 Schema Details

### `auth.py`

| Schema | Purpose |
|--------|---------|
| `LoginRequest` | Email + password for authentication |
| `TokenResponse` | Access token + refresh token + token type |
| `TokenData` | Decoded token payload (subject, type) |

### `user.py`

| Schema | Fields |
|--------|--------|
| `UserCreate` | `email`, `password`, `full_name`, `tenant_id`, `role_ids` |
| `UserUpdate` | All fields optional |
| `UserResponse` | `id`, `email`, `full_name`, `tenant_id`, `is_active`, `roles`, timestamps |

### `role.py`

| Schema | Fields |
|--------|--------|
| `RoleCreate` | `name`, `description`, `permissions` (JSON) |
| `RoleUpdate` | All fields optional |
| `RoleResponse` | `id`, `name`, `description`, `permissions`, `is_system_role`, timestamps |

### `hypervisor.py`

| Schema | Fields |
|--------|--------|
| `HypervisorCreate` | `name`, `type`, `host`, `port`, `username`, `password`, `tenant_id` |
| `HypervisorUpdate` | All fields optional |
| `HypervisorResponse` | `id`, `name`, `type`, `host`, `status`, timestamps |

### `vm.py`

| Schema | Fields |
|--------|--------|
| `VMCreate` | `name`, `hypervisor_id`, `vcpus`, `memory_mb`, `disk_size_gb`, `os_type` |
| `VMUpdate` | All fields optional |
| `VMResponse` | `id`, `name`, VM specs, `status`, `compatibility_status`, timestamps |

### `migration.py`

| Schema | Fields |
|--------|--------|
| `MigrationCreate` | `vm_id`, `strategy` |
| `MigrationUpdate` | `status`, `error_message` |
| `MigrationResponse` | `id`, `vm_id`, `strategy`, `status`, timing fields, timestamps |

---

## 🔒 Validation

Schemas enforce:
- **Email format** validation via `pydantic[email]`
- **Password strength** requirements (min 8 chars, mixed case, digit)
- **Enum constraints** for status, type, and strategy fields
- **UUID format** for all ID references
- **Required vs optional** field distinction between create and update operations