# 🗄 CRUD Operations (`crud/`)

Database access layer implementing Create, Read, Update, Delete operations for all ShiftWise resources. All CRUD functions enforce multi-tenancy by scoping queries to the current user's `tenant_id`.

---

## 📁 Files

| File | Resource | Description |
|------|----------|-------------|
| `user.py` | `User` | User account operations with tenant isolation |
| `role.py` | `Role` | Role management (system + custom roles) |

> **🚧 Planned:** `hypervisor.py`, `vm.py`, `migration.py` CRUD modules will be added as the Discovery, Analyzer, and Migrator modules are implemented.

---

## 🏗 CRUD Pattern

All CRUD modules follow the same pattern:

```python
def get(db: Session, id: UUID, tenant_id: str) -> Model | None:
    """Retrieve a single record by ID, scoped to tenant."""

def get_multi(db: Session, tenant_id: str, skip: int, limit: int) -> list[Model]:
    """Retrieve paginated records for a tenant."""

def create(db: Session, obj_in: CreateSchema, tenant_id: str) -> Model:
    """Create a new record within a tenant."""

def update(db: Session, db_obj: Model, obj_in: UpdateSchema) -> Model:
    """Update an existing record."""

def delete(db: Session, id: UUID, tenant_id: str) -> Model | None:
    """Delete a record. System records may be protected from deletion."""
```

---

## 🔐 Multi-Tenancy Enforcement

Every query automatically includes a `tenant_id` filter:

```python
# All reads are tenant-scoped
db.query(User).filter(
    User.id == user_id,
    User.tenant_id == current_user.tenant_id  # ← Tenant isolation
).first()
```

The `super_admin` role can optionally bypass tenant scoping for cross-tenant operations.

---

## 📄 Module Details

### `user.py`

| Function | Description |
|----------|-------------|
| `get_user(db, id, tenant_id)` | Get user by UUID within tenant |
| `get_user_by_email(db, email)` | Get user by email (login, uniqueness check) |
| `get_users(db, tenant_id, skip, limit)` | List users with pagination |
| `create_user(db, user_in, tenant_id)` | Create user with hashed password and role assignment |
| `update_user(db, user, user_in)` | Update user fields (partial update supported) |
| `delete_user(db, id, tenant_id)` | Soft/hard delete user |
| `authenticate(db, email, password)` | Verify credentials, return user or `None` |

### `role.py`

| Function | Description |
|----------|-------------|
| `get_role(db, id)` | Get role by UUID |
| `get_role_by_name(db, name)` | Get role by name (e.g., `"admin"`) |
| `get_roles(db, skip, limit)` | List all roles |
| `create_role(db, role_in)` | Create custom role |
| `update_role(db, role, role_in)` | Update role permissions |
| `delete_role(db, id)` | Delete custom role (system roles are protected) |
