# 🔧 Core Module (`core/`)

The core module provides the foundational infrastructure shared across all layers of the ShiftWise backend.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `config.py` | Application configuration via Pydantic Settings |
| `database.py` | SQLAlchemy engine, session factory, and initialization |
| `security.py` | JWT token management and bcrypt password hashing |
| `kubevirt_client.py` | Kubernetes/KubeVirt API client with 3 connection modes |

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
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `30` | Access token TTL (minutes) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `int` | `7` | Refresh token TTL (days) |

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

---

## 🗄 `database.py` — Database Engine

Initializes the SQLAlchemy async-ready engine and session factory.

| Component | Detail |
|-----------|--------|
| Engine | `create_engine` with connection pooling |
| Session | `sessionmaker` with `autocommit=False`, `autoflush=False` |
| `init_db()` | Creates all tables from registered models |
| `get_db()` | Provides a scoped session per request (used as FastAPI dependency) |

---

## 🔐 `security.py` — Authentication & Hashing

### Password Hashing

| Function | Description |
|----------|-------------|
| `get_password_hash(password)` | Hash plaintext with bcrypt |
| `verify_password(plain, hashed)` | Verify plaintext against hash |
| `validate_password_strength(password)` | Enforce policy: min 8 chars, mixed case, digit |

Passwords longer than 72 bytes are safely truncated before hashing (bcrypt limitation).

### JWT Tokens

| Function | Description |
|----------|-------------|
| `create_access_token(subject, expires_delta?)` | Generate short-lived access token |
| `create_refresh_token(subject, expires_delta?)` | Generate long-lived refresh token |
| `decode_token(token)` | Decode and validate a JWT, returns payload or `None` |
| `verify_token_type(payload, type)` | Verify token is `access` or `refresh` |

---

## ☸️ `kubevirt_client.py` — KubeVirt Client

Provides a unified interface to interact with Kubernetes/KubeVirt APIs regardless of the connection mode.

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

### Key Operations

| Method | Description |
|--------|-------------|
| `list_namespaces()` | List all Kubernetes namespaces |
| `list_vms(namespace)` | List KubeVirt VirtualMachine resources |
| `get_vm(name, namespace)` | Get a specific VM by name |
| `create_vm(spec, namespace)` | Create a VirtualMachine from a spec dict |
| `delete_vm(name, namespace)` | Delete a VirtualMachine |

### Usage

```python
from app.core.kubevirt_client import get_kubevirt_client

client = get_kubevirt_client()
vms = client.list_vms(namespace="migration-ns")
