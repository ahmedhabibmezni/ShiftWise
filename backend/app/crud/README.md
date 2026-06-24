# 🗄 CRUD Operations (`crud/`)

Database access layer implementing Create, Read, Update, Delete operations for all ShiftWise resources.

---

## 📁 Files

| File | Resource | Description |
|------|----------|-------------|
| `user.py` | `User` | User account operations + authentication |
| `role.py` | `Role` | System and custom role management |
| `hypervisor.py` | `Hypervisor` | Hypervisor connection operations |
| `vm.py` | `VirtualMachine` | VM inventory operations |
| `migration.py` | `Migration` | Migration lifecycle operations |
| `conversion.py` | `ConversionGroup` / `ConversionJob` / `ConversionAttempt` | Disk conversion tracking |
| `cluster_config.py` | `ClusterConnectionConfig` / `ClusterConfigEvent` | Per-tenant cluster connection config — sole reader/writer of the Fernet-encrypted `*_ciphertext` columns; scope resolution + append-only audit (feature 002) |

---

## 🏗 Conventions

- Primary keys are `int`.
- List functions are paginated (`skip`, `limit`) and each has a matching `*_count` function.
- `create_user` and `create_role` take a typed Pydantic schema; `create_hypervisor`, `create_vm`, and `create_migration` take a validated `dict` plus an explicit `tenant_id`.
- Public `update_*` functions silently drop protected fields (e.g. `status`, `target_namespace`). Worker-only status setters (`set_migration_status`, `set_group_status`, `set_job_status`) bypass that guard.

---

## 🔐 Multi-Tenancy

`hypervisor`, `vm`, `migration`, and `conversion` read/update/delete functions accept an optional `tenant_id`. When supplied, the query is filtered to that tenant, preventing cross-tenant access:

```python
# Scoped to the caller's tenant — returns None if the VM belongs to another tenant
crud.vm.get_vm(db, vm_id, tenant_id=current_user.tenant_id)
```

Superusers may omit `tenant_id` to operate across tenants. `Role` has no tenant; `User` carries `tenant_id` and is filtered by the route handlers.

---

## 📄 Module Details

### `user.py`

| Function | Description |
|----------|-------------|
| `get_user(db, user_id)` | Get user by ID |
| `get_user_by_email(db, email)` | Get user by email (login, uniqueness check) |
| `get_user_by_username(db, username)` | Get user by username |
| `get_users(db, skip, limit, tenant_id=…, …)` | Paginated list with tenant/status/search filters |
| `get_users_count(db, …)` | Count matching users |
| `create_user(db, user: UserCreate)` | Create user with hashed password and role assignment |
| `update_user(db, user_id, user_update)` | Partial update (email/username uniqueness, role reassignment) |
| `delete_user(db, user_id)` | Hard delete user |
| `authenticate_user(db, email, password)` | Verify credentials; return `User` or `None` |
| `get_users_by_tenant(db, tenant_id, skip, limit)` | List users for a specific tenant |
| `add_role_to_user(db, user_id, role_id)` | Assign a role to a user |
| `remove_role_from_user(db, user_id, role_id)` | Remove a role from a user |

### `role.py`

| Function | Description |
|----------|-------------|
| `get_role(db, role_id)` | Get role by ID |
| `get_role_by_name(db, name)` | Get role by name (e.g. `"admin"`) |
| `get_roles(db, skip, limit, …)` | Paginated list with active/search filters |
| `get_roles_count(db, …)` | Count matching roles |
| `create_role(db, role: RoleCreate)` | Create a custom (non-system) role |
| `update_role(db, role_id, role_update)` | Update role (system roles rejected) |
| `delete_role(db, role_id)` | Delete a custom role (rejected if users still assigned) |
| `create_system_roles(db)` | Seed the 4 system roles if absent; **reconcile** the `permissions` of existing system roles to the `ROLE_PERMISSIONS` matrix (so a matrix change propagates to deployments seeded earlier) |
| `get_role_users_count(db, role_id)` | Count users assigned to a role |

### `hypervisor.py`

| Function | Description |
|----------|-------------|
| `get_hypervisor(db, hypervisor_id, tenant_id=…)` | Get hypervisor by ID |
| `get_hypervisor_by_name(db, name)` | Get hypervisor by name |
| `get_hypervisors(db, skip, limit, …)` | Paginated list with type/status/search filters |
| `get_hypervisors_count(db, …)` | Count matching hypervisors |
| `create_hypervisor(db, data, tenant_id)` | Create hypervisor (initial status `UNKNOWN`) |
| `update_hypervisor(db, hypervisor_id, update_data, tenant_id=…)` | Partial update |
| `delete_hypervisor(db, hypervisor_id, tenant_id=…)` | Delete hypervisor (VM FKs `SET NULL`) |

### `vm.py`

| Function | Description |
|----------|-------------|
| `get_vm(db, vm_id, tenant_id=…)` | Get VM by ID |
| `get_vm_by_name(db, name)` | Get VM by name |
| `get_vms(db, skip, limit, …)` | Paginated list with status/compatibility/hypervisor/search filters |
| `get_vms_count(db, …)` | Count matching VMs |
| `create_vm(db, data, tenant_id)` | Create VM (initial `DISCOVERED` / `UNKNOWN`) |
| `update_vm(db, vm_id, update_data, tenant_id=…)` | Partial update (`status` / `compatibility_status` protected) |
| `delete_vm(db, vm_id, tenant_id=…)` | Delete VM (migrations cascade) |

### `migration.py`

| Function | Description |
|----------|-------------|
| `get_migration(db, migration_id, tenant_id=…)` | Get migration by ID |
| `get_migrations(db, skip, limit, …)` | Paginated list with status/strategy/VM filters |
| `get_migrations_count(db, …)` | Count matching migrations |
| `create_migration(db, data, tenant_id, target_namespace)` | Create migration (initial `PENDING`) |
| `update_migration(db, migration_id, update_data, tenant_id=…)` | Partial update (`status` / `target_namespace` protected) |
| `delete_migration(db, migration_id, tenant_id=…)` | Delete migration. Rejected while active (`ValueError`→400); rejected with `MigrationHasAuditTrail`→409 when audit events reference it (append-only retention — the FK blocks the delete). Succeeds (204) only for a migration with no events. |
| `set_migration_status(db, migration_id, status)` | Worker status setter (auto-stamps timing/outcome) |
| `update_migration_progress(db, migration_id, …)` | Update progress fields |
| `fail_migration(db, migration_id, …)` | Stamp error code/message |

### `conversion.py`

| Group | Functions |
|-------|-----------|
| Groups | `get_group`, `get_group_by_uuid`, `list_groups`, `count_groups`, `create_group`, `update_group`, `set_group_status`, `recompute_group_status`, `delete_group` |
| Jobs | `get_job`, `list_jobs_for_group`, `create_job`, `update_job`, `set_job_status` |
| Attempts | `create_attempt`, `finalize_attempt` |
