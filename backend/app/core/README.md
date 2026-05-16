# 🔧 Core Module (`core/`)

The core module provides the foundational infrastructure shared across all layers of the ShiftWise backend.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `config.py` | Application configuration via Pydantic Settings |
| `database.py` | SQLAlchemy engine, session factory, and table initialization |
| `security.py` | JWT token management and bcrypt password hashing |
| `kubevirt_client.py` | Kubernetes/KubeVirt API client with 3 connection modes |
| `celery_app.py` | Celery application instance for the async migration pipeline |
| `redis_client.py` | Redis connection helper for the auth token store |
| `refresh_token_store.py` | Refresh-token family tracking, rotation, and reuse detection |
| `login_throttle.py` | Sliding-window brute-force protection for `/auth/login` |
| `constants.py` | Shared constants (valid RBAC resources and actions) |

---

## ⚙️ `config.py` — Settings

Uses `pydantic-settings` to load and validate environment variables from `.env`.

### Configuration Groups

<details>
<summary><strong>Application</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_NAME` | `str` | `ShiftWise` | Application display name |
| `APP_VERSION` | `str` | `1.0.0` | Semantic version |
| `DEBUG` | `bool` | `False` | Debug mode toggle |
| `SERVER_HOST` | `str` | `127.0.0.1` | Host interface for `python app/main.py` |
| `LOG_LEVEL` | `str` | `INFO` | Logging level (`DEBUG`…`CRITICAL`) |

</details>

<details>
<summary><strong>Database</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_HOST` | `str` | *(required)* | PostgreSQL hostname |
| `DATABASE_PORT` | `int` | `5432` | PostgreSQL port |
| `DATABASE_NAME` | `str` | *(required)* | Database name |
| `DATABASE_USER` | `str` | *(required)* | Database user |
| `DATABASE_PASSWORD` | `str` | *(required)* | Database password |
| `DATABASE_POOL_SIZE` | `int` | `10` | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | `int` | `20` | Max overflow connections |

The `DATABASE_URL` property auto-constructs the connection URI with URL-encoded credentials.

</details>

<details>
<summary><strong>Security & JWT</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECRET_KEY` | `str` | *(required)* | JWT signing key |
| `ALGORITHM` | `str` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `15` | Access token TTL (minutes) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `int` | `7` | Refresh token TTL (days) |
| `REFRESH_COOKIE_NAME` | `str` | `shiftwise_refresh` | Refresh-token cookie name |
| `REFRESH_COOKIE_PATH` | `str` | `/api/v1/auth` | Cookie path scope |
| `REFRESH_COOKIE_SAMESITE` | `str` | `strict` | Cookie `SameSite` attribute |
| `REFRESH_COOKIE_SECURE` | `bool` | `False` | Send cookie over HTTPS only (set `True` in production) |
| `REFRESH_COOKIE_DOMAIN` | `str?` | `None` | Cookie domain (empty = host-only) |

</details>

<details>
<summary><strong>Kubernetes / OpenShift</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `KUBERNETES_MODE` | `str` | `kubeconfig` | Connection mode: `kubeconfig`, `incluster`, `custom` |
| `KUBECONFIG_PATH` | `str?` | `./config/kubeconfig` | Path to kubeconfig file |
| `USE_IN_CLUSTER` | `bool` | `False` | Use in-cluster ServiceAccount |
| `KUBERNETES_API_URL` | `str?` | `None` | Custom K8s API URL |
| `KUBERNETES_TOKEN` | `str?` | `None` | Custom bearer token |
| `KUBERNETES_VERIFY_SSL` | `bool` | `False` | Verify SSL certificates |
| `KUBERNETES_DEFAULT_NAMESPACE` | `str` | `default` | Default VM namespace |

</details>

<details>
<summary><strong>CORS & API</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BACKEND_CORS_ORIGINS` | `list` | `[]` | Allowed CORS origins (JSON list or comma-separated) |
| `API_V1_PREFIX` | `str` | `/api/v1` | API v1 path prefix |

</details>

<details>
<summary><strong>Redis, Celery & Login Throttle</strong></summary>

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REDIS_AUTH_URL` | `str` | `redis://localhost:6379/1` | Redis URL for the refresh-token store |
| `CELERY_BROKER_URL` | `str` | `redis://localhost:6379/0` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `str` | `redis://localhost:6379/0` | Celery result backend |
| `CELERY_TASK_ALWAYS_EAGER` | `bool` | `False` | Run tasks synchronously (tests) |
| `LOGIN_THROTTLE_MAX_ATTEMPTS` | `int` | `5` | Failed logins before lockout (`≤0` disables) |
| `LOGIN_THROTTLE_WINDOW_SECONDS` | `int` | `900` | Throttle sliding-window length |

</details>

<details>
<summary><strong>Migration Pipeline</strong></summary>

Additional `ANALYZER_*`, `CONVERTER_*`, `ADAPTER_*`, and `MIGRATOR_*` settings tune the migration pipeline — ML confidence threshold, NFS transit paths, container images, job timeouts, and optional per-tenant `ResourceQuota` limits. See `config.py` and `.env.example` for the full list.

</details>

---

## 🗄 `database.py` — Database Engine

Initializes the **synchronous** SQLAlchemy 2.0 engine and session factory.

| Component | Detail |
|-----------|--------|
| `Base` | `DeclarativeBase` subclass — parent of all ORM models |
| Engine | `create_engine` with `pool_pre_ping`, configurable pool size/overflow |
| Session | `sessionmaker` with `autocommit=False`, `autoflush=False` |
| `init_db()` | Creates all tables from registered models — **development only**; use Alembic in production |
| `get_db()` | Yields a scoped session per request (FastAPI dependency) |

---

## 🔐 `security.py` — Authentication & Hashing

### Password Hashing

| Function | Description |
|----------|-------------|
| `get_password_hash(password)` | Hash plaintext with bcrypt |
| `verify_password(plain, hashed)` | Verify plaintext against a hash |
| `validate_password_strength(password)` | Enforce policy: min 8 chars, mixed case, digit |

Passwords longer than 72 bytes are safely truncated before hashing (bcrypt limitation).

### JWT Tokens

| Function | Description |
|----------|-------------|
| `create_access_token(subject, expires_delta=None)` | Generate a short-lived access token |
| `create_refresh_token(subject, family_id, jti, expires_delta=None)` | Generate a refresh token carrying its `fam` (family) and `jti` claims for reuse detection |
| `decode_token(token)` | Decode and validate a JWT; returns the payload or `None` |
| `verify_token_type(payload, token_type)` | Verify the token is `access` or `refresh` |

Refresh-token rotation, family invalidation, and reuse detection are handled in `refresh_token_store.py` against Redis.

---

## ☸️ `kubevirt_client.py` — KubeVirt Client

`KubeVirtClient` provides a unified interface to Kubernetes/KubeVirt APIs regardless of the connection mode.

### Connection Modes

```
┌──────────────────────────────────────────────────────────────┐
│                    KubeVirtClient                             │
│                                                               │
│  Mode: kubeconfig    Mode: incluster    Mode: custom          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │ Read file at │   │ Use mounted  │   │ API URL +    │     │
│  │ KUBECONFIG_  │   │ ServiceAccount│  │ Bearer token │     │
│  │ PATH         │   │ credentials  │   │ from env     │     │
│  └──────────────┘   └──────────────┘   └──────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

### Representative Operations

| Method | Description |
|--------|-------------|
| `list_vms(namespace)` | List KubeVirt `VirtualMachine` resources |
| `get_vm(name, namespace)` | Get a specific VM by name |
| `create_vm(name, cpu, memory, ...)` | Create a `VirtualMachine` |
| `delete_vm(name, namespace)` | Delete a `VirtualMachine` |
| `start_vm` / `stop_vm` | Start or stop a VM |
| `list_vmis(namespace)` | List running `VirtualMachineInstance` resources |

These back the `/api/v1/kubevirt` router endpoints; `KubeVirtClient` also exposes `core_api`, `storage_api`, and `batch_api` for namespace, StorageClass, and Job operations.

### Usage

```python
from app.core.kubevirt_client import KubeVirtClient

client = KubeVirtClient()
vms = client.list_vms(namespace="shiftwise-acme")
```
