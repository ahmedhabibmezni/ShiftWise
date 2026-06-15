# 🧪 Test Suite (`tests/`)

Test coverage for the ShiftWise backend API, services, and migration pipeline. Coverage target: **> 80%** (currently ~85%).

---

## 📁 Test Files

| File | Area |
|------|------|
| `conftest.py` | Shared pytest fixtures |
| `test_complete_api.py` | Full API endpoint suite across all routers |
| `test_user_management.py` | User CRUD, RBAC, multi-tenancy isolation |
| `test_login_audit.py` | Login audit trail (`last_login_at` / `last_login_ip`) |
| `test_login_throttle.py` | Brute-force login throttling |
| `test_health.py` | `/health` probe (`healthy` / `degraded` / `unhealthy`) |
| `test_kubevirt_client.py` | KubeVirt client connection modes |
| `test_analyzer.py` | Compatibility rules engine, feature extractor, model degraded mode |
| `test_analyzer_live.py` | Analyzer integration against a live model artifact |
| `test_compatibility_scoring.py` | Intervention-based scoring (`100 − Σ penalties`), incl. physical (P2V) driver-injection rule |
| `test_strategy.py` | Score → `MigrationStrategy` band mapping (`recommend_strategy`) |
| `test_migration_auto_strategy.py` | Auto strategy selection at migration creation (fallback `AUTO`) |
| `test_converter.py` | Conversion plan, Kubernetes Job manifests, error catalog (incl. vSphere + P2V raw cases) |
| `test_p2v_capture.py` | Physical (P2V) `dd\|gzip` raw capture + gunzip-to-file streaming |
| `test_adapter.py` | Adapter error catalog, Job manifests, orchestration (K8s mocked), P2V initramfs branch |
| `test_discovery_physical.py` | Physical (P2V) SSH fact collection + `lsblk` disk plan |
| `test_discovery_vsphere.py` | vSphere/ESXi `pyVmomi` discovery mapping (getattr fakes) |
| `test_migrator.py` | PVC sizing, VM manifest, `MigratorService` (K8s mocked) |
| `test_migrator_p1.py` | Transit-NFS discovery, namespace lifecycle, error classification |
| `test_namespace_quota.py` | Opt-in per-tenant `ResourceQuota` |
| `test_celery_tasks.py` | Celery task wiring (eager mode) |
| `test_hyperv_discovery.py` | Hyper-V discovery connector |
| `test_hyperv_sync.py` | Hyper-V end-to-end sync (INSERT / UPDATE / ARCHIVE) |
| `test_kvm_sync.py` | KVM end-to-end sync |
| `test_proxmox_sync.py` | Proxmox VE end-to-end sync |
| `test_vmware_workstation_sync.py` | VMware Workstation end-to-end sync |
| `demo.py` | Quick demo / smoke-test script |

The `test_*_sync.py` files and `test_analyzer_live.py` are integration tests that require a running server or live artifacts.

---

## 🚀 Running Tests

```bash
cd backend

# Run the full suite
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=app --cov-report=html --cov-report=term

# Run a specific test file
pytest tests/test_complete_api.py -v

# Run by name pattern
pytest tests/ -v -k "test_login"

# Stop on first failure
pytest tests/ -v -x
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

Protected endpoints are tested with a JWT obtained through the login endpoint:

```python
# 1. Login to get the access token
login_response = client.post("/api/v1/auth/login", json={
    "email": "admin@shiftwise.io",
    "password": "SecurePass123",
})
token = login_response.json()["access_token"]

# 2. Use the token in subsequent requests
response = client.get(
    "/api/v1/users",
    headers={"Authorization": f"Bearer {token}"},
)
```

The login throttle and refresh-token store run against an in-memory `fakeredis` instance in tests, so the suite does not need a live Redis broker.

---

## 📋 Coverage Areas

| Layer | Tests |
|-------|-------|
| API & routers | `test_complete_api.py` |
| Users / RBAC / multi-tenancy | `test_user_management.py` |
| Auth hardening | `test_login_audit.py`, `test_login_throttle.py`, `test_health.py` |
| KubeVirt client | `test_kubevirt_client.py` |
| Analyzer | `test_analyzer.py`, `test_analyzer_live.py` |
| Converter | `test_converter.py` |
| Adapter | `test_adapter.py` |
| Migrator | `test_migrator.py`, `test_migrator_p1.py`, `test_namespace_quota.py` |
| Celery orchestration | `test_celery_tasks.py` |
| Discovery / sync | `test_hyperv_discovery.py`, `test_hyperv_sync.py`, `test_kvm_sync.py`, `test_proxmox_sync.py`, `test_vmware_workstation_sync.py` |

---

## 🔧 Configuration

Tests use the same `.env` configuration as the application. For isolated runs, point at a dedicated test database:

```bash
DATABASE_NAME=shiftwise_test
```

> **Tip:** configure default test options in `pytest.ini` or `pyproject.toml`:
> ```ini
> [pytest]
> testpaths = tests
> python_files = test_*.py
> python_functions = test_*
> addopts = -v --tb=short
> ```
