# ⚙️ ShiftWise Backend

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square)](https://sqlalchemy.org)

The ShiftWise backend is a **FastAPI** application providing RESTful APIs for intelligent VM-to-OpenShift migration. It handles authentication, authorization, VM inventory management, hypervisor connections, migration orchestration, and direct KubeVirt cluster operations.

---

## 📁 Directory Structure

```
backend/
├── app/                        # Application package
│   ├── api/                    # API layer (routers, dependencies)
│   │   ├── deps.py             # Dependency injection (auth, DB, RBAC)
│   │   └── v1/                 # API v1 route handlers
│   ├── core/                   # Core infrastructure
│   │   ├── config.py           # Settings (Pydantic BaseSettings)
│   │   ├── database.py         # SQLAlchemy engine & session factory
│   │   ├── security.py         # JWT tokens & bcrypt hashing
│   │   └── kubevirt_client.py  # Kubernetes/KubeVirt API wrapper
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── crud/                   # Database CRUD operations
│   ├── services/               # Business logic services
│   └── main.py                 # FastAPI application entry point
├── tests/                      # Test suite
├── alembic/                    # Database migration scripts
├── config/                     # Config files (kubeconfig)
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

Edit `.env` with your values:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_HOST` | PostgreSQL host | `localhost` |
| `DATABASE_PORT` | PostgreSQL port | `5432` |
| `DATABASE_NAME` | Database name | `shiftwise_db` |
| `DATABASE_USER` | Database user | `postgres` |
| `DATABASE_PASSWORD` | Database password | *(required)* |
| `SECRET_KEY` | JWT signing key | *(required)* |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `KUBERNETES_MODE` | K8s connection mode | `kubeconfig` |
| `KUBECONFIG_PATH` | Path to kubeconfig | `./config/kubeconfig` |
| `DEBUG` | Enable debug mode | `False` |
| `LOG_LEVEL` | Logging level | `INFO` |

### 3. Database

```bash
# Create database (first time only)
python create_db.py

# Initialize tables and seed default roles
python init_db.py
```

### 4. Run

```bash
# Development (with auto-reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 📡 API Endpoints

**Base URL:** `/api/v1`

### Authentication

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/auth/login` | Obtain JWT tokens | ❌ |
| `POST` | `/auth/refresh` | Refresh access token | 🔑 |
| `GET` | `/auth/me` | Current user profile | 🔑 |

### Users

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/users` | List users (tenant-scoped) | `admin` |
| `POST` | `/users` | Create user | `admin` |
| `GET` | `/users/{id}` | Get user by ID | `admin` |
| `PUT` | `/users/{id}` | Update user | `admin` |
| `DELETE` | `/users/{id}` | Delete user | `super_admin` |

### Roles

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/roles` | List roles | `admin` |
| `POST` | `/roles` | Create custom role | `super_admin` |
| `GET` | `/roles/{id}` | Get role details | `admin` |
| `PUT` | `/roles/{id}` | Update role | `super_admin` |
| `DELETE` | `/roles/{id}` | Delete custom role | `super_admin` |

### Virtual Machines

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/vms` | List VMs | `viewer` |
| `POST` | `/vms` | Create/register VM | `user` |
| `GET` | `/vms/{id}` | Get VM details | `viewer` |
| `PUT` | `/vms/{id}` | Update VM | `user` |
| `DELETE` | `/vms/{id}` | Delete VM | `admin` |

### Hypervisors

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/hypervisors` | List hypervisors | `admin` |
| `POST` | `/hypervisors` | Register hypervisor | `admin` |
| `GET` | `/hypervisors/{id}` | Get hypervisor details | `admin` |
| `PUT` | `/hypervisors/{id}` | Update hypervisor | `admin` |
| `DELETE` | `/hypervisors/{id}` | Remove hypervisor | `admin` |

### Migrations

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/migrations` | List migrations | `viewer` |
| `POST` | `/migrations` | Create migration | `user` |
| `GET` | `/migrations/{id}` | Get migration details | `viewer` |
| `PUT` | `/migrations/{id}` | Update migration | `user` |
| `DELETE` | `/migrations/{id}` | Cancel migration | `admin` |

### KubeVirt / OpenShift

| Method | Endpoint | Description | Min Role |
|--------|----------|-------------|----------|
| `GET` | `/kubevirt/namespaces` | List namespaces | `admin` |
| `GET` | `/kubevirt/vms` | List KubeVirt VMs | `admin` |
| `GET` | `/kubevirt/vms/{name}` | Get KubeVirt VM | `admin` |
| `POST` | `/kubevirt/vms` | Create KubeVirt VM | `admin` |
| `DELETE` | `/kubevirt/vms/{name}` | Delete KubeVirt VM | `admin` |

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

[//]: # (- [`tests/README.md`]&#40;tests/README.md&#41; — Testing guide)