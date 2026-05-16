# 📦 Application Package (`app/`)

The `app/` package is the core of the ShiftWise backend. It follows a layered architecture pattern that separates concerns across distinct modules.

---

## 🏗 Architecture Layers

```
                ┌─────────────────────────────┐
                │   main.py (Entry Point)     │
                │   FastAPI app, CORS, routers │
                └──────────────┬──────────────┘
                               │
                ┌──────────────▼──────────────┐
                │   api/ (HTTP Layer)          │
                │   Routers + deps.py          │
                └──────────────┬──────────────┘
                               │
        ┌──────────────┬───────┴───────┬──────────────┐
┌───────▼──────┐ ┌─────▼──────┐ ┌──────▼─────┐ ┌──────▼──────┐
│ schemas/     │ │ crud/      │ │ services/  │ │ tasks/      │
│ Validation   │ │ DB access  │ │ Pipeline   │ │ Celery jobs │
└──────────────┘ └─────┬──────┘ └──────┬─────┘ └──────┬──────┘
                       │               │              │
                       └───────┬───────┴──────────────┘
                               │
                       ┌───────▼───────┐
                       │ models/       │
                       │ ORM Models    │
                       └───────┬───────┘
                               │
                       ┌───────▼───────────────┐
                       │ core/                 │
                       │ Config, DB, Security, │
                       │ KubeVirt, Celery,     │
                       │ Redis                 │
                       └───────────────────────┘
```

---

## 📄 `main.py` — Application Entry Point

The FastAPI application instance is created in `main.py`. It configures:

| Aspect | Detail |
|--------|--------|
| **CORS** | Explicit origin / method / header allowlists from `BACKEND_CORS_ORIGINS`, with `allow_credentials=True` |
| **Routers** | 8 API v1 routers mounted under `/api/v1` |
| **Documentation** | Swagger UI at `/docs`, ReDoc at `/redoc`, OpenAPI at `/openapi.json` |
| **Lifecycle** | `lifespan` context manager — runs `init_db()` on startup |
| **Exception Handling** | Global handler; exposes exception type + request path when `DEBUG=True` |
| **Health Check** | `GET /health` probes PostgreSQL and the auth Redis (`healthy` / `degraded` / `unhealthy`) |

### Mounted Routers

| Router | Prefix | Tags |
|--------|--------|------|
| `auth` | `/api/v1/auth` | Authentication |
| `users` | `/api/v1/users` | Users |
| `roles` | `/api/v1/roles` | Roles |
| `vms` | `/api/v1/vms` | VirtualMachines |
| `hypervisors` | `/api/v1/hypervisors` | Hypervisors |
| `migrations` | `/api/v1/migrations` | Migrations |
| `kubevirt` | `/api/v1/kubevirt` | KubeVirt / OpenShift |
| `conversions` | `/api/v1/conversions` | Conversions |

---

## 📂 Sub-Packages

| Package | Purpose | Documentation |
|---------|---------|---------------|
| [`api/`](api/README.md) | HTTP layer — route handlers and dependency injection | API layer docs |
| [`core/`](core/README.md) | Config, database, security, KubeVirt client, Celery, Redis | Core module docs |
| [`models/`](models/README.md) | SQLAlchemy ORM model definitions | Models reference |
| [`schemas/`](schemas/README.md) | Pydantic v2 request/response schemas | Schemas reference |
| [`crud/`](crud/README.md) | Database CRUD operations | CRUD reference |
| [`services/`](services/README.md) | Business logic — discovery, analyzer, converter, adapter, migrator | Services docs |
| `tasks/` | Celery tasks — migration & conversion pipeline orchestration | — |
| `ml/` | ML training scripts and the serialized compatibility model | — |
