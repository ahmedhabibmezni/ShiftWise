# 🧪 Test Suite (`tests/`)

Comprehensive test coverage for the ShiftWise backend API, services, and integrations.

---

## 📁 Test Files

| File | Lines | Description |
|------|-------|-------------|
| `test_complete_api.py` | ~750 | Full API endpoint test suite across all routers |
| `test_user_management.py` | ~900 | Deep user management tests (CRUD, multi-tenancy, RBAC) |
| `test_kubevirt_client.py` | ~120 | KubeVirt client integration tests |
| `test_discovery.py` | ~70 | Discovery service unit tests |
| `test_discovery_comprehensive.py` | ~280 | Extended discovery test scenarios |
| `demo.py` | ~30 | Quick demo/smoke test script |

---

## 🚀 Running Tests

```bash
cd backend

# Run full suite
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=app --cov-report=html --cov-report=term

# Run specific test file
pytest tests/test_complete_api.py -v

# Run specific test by name pattern
pytest tests/ -v -k "test_login"

# Run with parallel execution (requires pytest-xdist)
pytest tests/ -v -n auto
```

---

## 🏗 Test Architecture

### Test Client

Tests use FastAPI's `TestClient` (based on `httpx`) for synchronous HTTP testing:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
response = client.post("/api/v1/auth/login", json={...})
assert response.status_code == 200
```

### Authentication in Tests

Protected endpoints are tested with JWT tokens obtained through the login endpoint:

```python
# 1. Login to get token
login_response = client.post("/api/v1/auth/login", json={
    "email": "admin@shiftwise.io",
    "password": "SecurePass123"
})
token = login_response.json()["access_token"]

# 2. Use token in subsequent requests
response = client.get(
    "/api/v1/users",
    headers={"Authorization": f"Bearer {token}"}
)
```

---

## 📋 Test Coverage Areas

### `test_complete_api.py`

| Area | Tests |
|------|-------|
| Health endpoints | `GET /`, `GET /health` |
| Auth flow | Login, token refresh, invalid credentials |
| User CRUD | Create, read, update, delete with RBAC |
| Role CRUD | System roles, custom roles, permission checks |
| VM operations | Register, list, update, delete VMs |
| Hypervisor operations | Register, connect, update, remove |
| Migration lifecycle | Create, track status, cancel |
| KubeVirt operations | Namespace listing, VM CRUD on cluster |

### `test_user_management.py`

| Area | Tests |
|------|-------|
| User creation | Valid data, duplicate email, missing fields |
| Multi-tenancy | Cross-tenant isolation, tenant-scoped queries |
| RBAC enforcement | Role-based access, permission denied scenarios |
| Password handling | Strength validation, bcrypt hashing |
| Edge cases | Inactive users, deleted accounts, role changes |

### `test_kubevirt_client.py`

| Area | Tests |
|------|-------|
| Connection modes | `kubeconfig`, `in-cluster`, `custom` |
| Namespace operations | List, validate |
| VM operations | Create, get, list, delete via KubeVirt API |
| Error handling | Connection failures, invalid specs |

### `test_discovery.py` / `test_discovery_comprehensive.py`

| Area | Tests |
|------|-------|
| VMware discovery | vSphere connection, VM enumeration |
| libvirt discovery | Domain listing via libvirt API |
| Hyper-V discovery | WMI-based VM detection |
| Error scenarios | Connection timeouts, auth failures |

---

## 🔧 Configuration

Tests use the same `.env` configuration as the application. For isolated testing, create a dedicated test database:

```bash
DATABASE_NAME=shiftwise_test_db
```

> **Tip:** Use `pytest.ini` or `pyproject.toml` to configure default test options:
> ```ini
> [pytest]
> testpaths = tests
> python_files = test_*.py
> python_functions = test_*
> addopts = -v --tb=short
> ```