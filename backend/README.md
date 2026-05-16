# ⚙️ ShiftWise Backend

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square)](https://sqlalchemy.org)

The ShiftWise backend is a **FastAPI** application providing RESTful APIs for intelligent VM-to-OpenShift migration. It handles authentication, authorization, VM inventory management, hypervisor connections, the migration pipeline (discovery → analysis → conversion → adaptation → migration), and direct KubeVirt cluster operations. The migration pipeline runs asynchronously on Celery workers backed by Redis.

---

## 📁 Directory Structure

```
backend/
├── app/                        # Application package
│   ├── api/                    # API layer (routers, dependencies)
│   │   ├── deps.py             # JWT auth, RBAC (check_permission), tenant scoping
│   │   └── v1/                 # API v1 route handlers (8 routers)
│   ├── core/                   # Core infrastructure
│   │   ├── config.py               # Settings (Pydantic Settings)
│   │   ├── database.py             # SQLAlchemy engine & session factory
│   │   ├── security.py             # JWT tokens & bcrypt hashing
│   │   ├── kubevirt_client.py      # Kubernetes/KubeVirt API wrapper
│   │   ├── celery_app.py           # Celery application instance
│   │   ├── redis_client.py         # Redis connection (auth store)
│   │   ├── refresh_token_store.py  # Refresh-token family rotation
│   │   ├── login_throttle.py       # Brute-force login protection
│   │   └── constants.py            # Shared constants
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic v2 request/response schemas
│   ├── crud/                   # Database CRUD operations
│   ├── services/               # Business logic (discovery, analyzer, converter, adapter, migrator)
│   ├── tasks/                  # Celery tasks (migration, conversion)
│   ├── ml/                     # ML training scripts + model artifacts
│   └── main.py                 # FastAPI application entry point
├── tests/                      # Test suite
├── alembic/                    # Database migration scripts
├── openshift/                  # OpenShift deployment manifests + deploy.sh
├── config/                     # Config files (kubeconfig)
├── Dockerfile                  # Container image (backend / worker / populator / adapter)
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── create_db.py                # One-time database creation script
└── init_db.py                  # Database initialization & seeding
```

---

## 🚀 Setup

### 1. Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Copy template
cp .env.example .env
```

Key variables (see `.env.example` for the complete list, including Analyzer / Converter / Adapter / Migrator settings):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_HOST` | PostgreSQL host | *(required)* |
| `DATABASE_PORT` | PostgreSQL port | `5432` |
| `DATABASE_NAME` | Database name | *(required, e.g. `shiftwise`)* |
| `DATABASE_USER` | Database user | *(required, e.g. `shiftwise`)* |
| `DATABASE_PASSWORD` | Database password | *(required)* |
| `SECRET_KEY` | JWT signing key (min 32 chars) | *(required)* |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `REDIS_AUTH_URL` | Redis URL for the refresh-token store | `redis://localhost:6379/1` |
| `CELERY_BROKER_URL` | Redis URL for the Celery broker | `redis://localhost:6379/0` |
| `KUBERNETES_MODE` | K8s connection mode (`kubeconfig`/`incluster`/`custom`) | `kubeconfig` |
| `KUBECONFIG_PATH` | Path to kubeconfig | `./config/kubeconfig` |
| `BACKEND_CORS_ORIGINS` | Allowed CORS origins (JSON list) | `[]` |
| `DEBUG` | Enable debug mode | `False` |
| `LOG_LEVEL` | Logging level | `INFO` |

> **Redis is required.** The `/api/v1/auth/*` endpoints use Redis (`REDIS_AUTH_URL`, DB 1) for refresh-token rotation and login throttling, and Celery uses Redis (DB 0) as its broker. Without Redis, authentication and the migration pipeline are unavailable.

### 3. Database

```bash
# Create database (first time only)
python create_db.py

# Initialize tables and seed the 4 system roles
python init_db.py
```

For production, manage the schema with Alembic instead of `init_db.py`:

```bash
alembic upgrade head
```

### 4. Run

```bash
# Development (with auto-reload)
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

The migration pipeline additionally requires a running Celery worker (and Redis). See `openshift/` for the full multi-service deployment.

---

## 📡 API Endpoints

**Base URL:** `/api/v1` · Full request/response detail: [`../docs/api-reference.md`](../docs/api-reference.md)

Authorization on non-auth endpoints is enforced by the `check_permission(resource, action)` dependency. Superusers bypass all permission checks. Every non-superuser request is scoped to the caller's `tenant_id`.

### Authentication — `/api/v1/auth`

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/login` | Authenticate; issue access token + refresh cookie | Public |
| `POST` | `/refresh` | Rotate refresh cookie, issue new access token | Refresh cookie |
| `POST` | `/logout` | Revoke the refresh-token family | Public |
| `GET` | `/me` | Current user profile, roles, computed permissions | Authenticated |
| `POST` | `/change-password` | Change own password | Authenticated |
| `GET` | `/verify` | Validate the current access token | Authenticated |

### Users — `/api/v1/users`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `POST` | `/` | Create user | `users:create` |
| `GET` | `/` | List users (tenant-scoped) | `users:read` |
| `GET` | `/tenant/{tenant_id}/count` | Count users in a tenant | `users:read` |
| `GET` | `/{user_id}` | Get user | `users:read` |
| `PUT` | `/{user_id}` | Update user | `users:update` |
| `DELETE` | `/{user_id}` | Delete user (self-deletion rejected) | `users:delete` |
| `POST` | `/{user_id}/roles/{role_id}` | Assign role to user | `users:update` |
| `DELETE` | `/{user_id}/roles/{role_id}` | Remove role from user | `users:update` |

### Roles — `/api/v1/roles`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `POST` | `/` | Create custom role | `roles:create` |
| `GET` | `/` | List roles | `roles:read` |
| `GET` | `/count` | Count roles | `roles:read` |
| `GET` | `/name/{role_name}` | Get role by name | `roles:read` |
| `POST` | `/init-system-roles` | Seed the 4 system roles | Superuser |
| `GET` | `/permissions/resources` | List assignable resources | `roles:read` |
| `GET` | `/{role_id}` | Get role | `roles:read` |
| `PUT` | `/{role_id}` | Update role | `roles:update` |
| `DELETE` | `/{role_id}` | Delete custom role (system roles protected) | `roles:delete` |
| `GET` | `/{role_id}/users/count` | Count users with a role | `roles:read` |

### Virtual Machines — `/api/v1/vms`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/` | List VMs (filter by status / compatibility / hypervisor) | `vms:read` |
| `POST` | `/` | Register a VM | `vms:create` |
| `GET` | `/stats/summary` | VM inventory statistics | `vms:read` |
| `GET` | `/analyze/stats` | Compatibility statistics | `vms:read` |
| `POST` | `/analyze/batch` | Analyze up to 20 VMs | `vms:update` |
| `GET` | `/{vm_id}` | Get VM | `vms:read` |
| `PUT` | `/{vm_id}` | Update VM | `vms:update` |
| `DELETE` | `/{vm_id}` | Delete VM | `vms:delete` |
| `POST` | `/{vm_id}/analyze` | Run compatibility analysis | `vms:update` |
| `POST` | `/{vm_id}/convert` | Trigger disk conversion | `conversions:create` |
| `GET` | `/{vm_id}/migrations` | Migration history for a VM | `vms:read` |

### Hypervisors — `/api/v1/hypervisors`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/` | List hypervisors | `hypervisors:read` |
| `POST` | `/` | Register a hypervisor | `hypervisors:create` |
| `GET` | `/stats/summary` | Hypervisor statistics | `hypervisors:read` |
| `POST` | `/test-connection` | Test connection credentials | `hypervisors:create` |
| `GET` | `/{hypervisor_id}` | Get hypervisor | `hypervisors:read` |
| `PUT` | `/{hypervisor_id}` | Update hypervisor | `hypervisors:update` |
| `DELETE` | `/{hypervisor_id}` | Delete hypervisor | `hypervisors:delete` |
| `GET` | `/{hypervisor_id}/vms` | VMs discovered from a hypervisor | `hypervisors:read` |
| `POST` | `/{hypervisor_id}/sync` | Run VM discovery / sync | `hypervisors:update` |

### Migrations — `/api/v1/migrations`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/` | List migrations | `migrations:read` |
| `POST` | `/` | Create a migration | `migrations:create` |
| `GET` | `/stats/summary` | Migration statistics | `migrations:read` |
| `GET` | `/{migration_id}` | Get migration | `migrations:read` |
| `PUT` | `/{migration_id}` | Update migration | `migrations:update` |
| `DELETE` | `/{migration_id}` | Delete migration | `migrations:delete` |
| `POST` | `/{migration_id}/start` | Enqueue the migration pipeline (Celery) | `migrations:update` |
| `POST` | `/{migration_id}/cancel` | Cancel a migration | `migrations:update` |
| `PUT` | `/{migration_id}/progress` | Update migration progress | `migrations:update` |

### KubeVirt / OpenShift — `/api/v1/kubevirt`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/vms` | List KubeVirt VirtualMachines | `vms:read` |
| `GET` | `/vms/{vm_name}` | Get a KubeVirt VM | `vms:read` |
| `GET` | `/vms/{vm_name}/status` | KubeVirt VM status | `vms:read` |
| `POST` | `/vms` | Create a KubeVirt VM | `vms:create` |
| `DELETE` | `/vms/{vm_name}` | Delete a KubeVirt VM | `vms:delete` |
| `POST` | `/vms/{vm_name}/start` | Start a KubeVirt VM | `vms:update` |
| `POST` | `/vms/{vm_name}/stop` | Stop a KubeVirt VM | `vms:update` |
| `GET` | `/vmis` | List VirtualMachineInstances | `vms:read` |
| `GET` | `/storage-classes` | List cluster StorageClasses | `vms:read` |
| `GET` | `/namespace-info` | Tenant namespace info | `vms:read` |

### Conversions — `/api/v1/conversions`

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/` | List conversion groups | `conversions:read` |
| `GET` | `/stats` | Conversion statistics | `conversions:read` |
| `GET` | `/{group_uuid}` | Get a conversion group | `conversions:read` |
| `POST` | `/{group_uuid}/cancel` | Cancel a conversion | `conversions:update` |
| `POST` | `/{group_uuid}/retry` | Retry a failed conversion | `conversions:update` |

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html

# Specific test files
pytest tests/test_complete_api.py -v
pytest tests/test_user_management.py -v
pytest tests/test_kubevirt_client.py -v
```

---

## 📚 Further Documentation

- [`app/README.md`](app/README.md) — Application package overview
- [`app/api/README.md`](app/api/README.md) — API layer details
- [`app/core/README.md`](app/core/README.md) — Core module documentation
- [`app/models/README.md`](app/models/README.md) — Database models reference
- [`app/schemas/README.md`](app/schemas/README.md) — Pydantic schemas reference
- [`app/crud/README.md`](app/crud/README.md) — CRUD operations reference
- [`app/services/README.md`](app/services/README.md) — Business logic services
- [`tests/README.md`](tests/README.md) — Testing guide
