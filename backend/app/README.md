# 📦 Application Package (`app/`)

The `app/` package is the core of the ShiftWise backend. It follows a layered architecture pattern that separates concerns across distinct modules.

---

## 🏗 Architecture Layers

```
                ┌─────────────────────────────┐
                │   main.py (Entry Point)      │
                │   FastAPI app, CORS, routers  │
                └──────────────┬──────────────┘
                               │
                ┌──────────────▼──────────────┐
                │   api/ (HTTP Layer)          │
                │   Route handlers, deps.py    │
                └──────────────┬──────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
  ┌───────▼───────┐   ┌───────▼───────┐   ┌────────▼────────┐
  │ schemas/      │   │ crud/         │   │ services/       │
  │ Validation    │   │ DB Operations │   │ Business Logic  │
  └───────────────┘   └───────┬───────┘   └─────────────────┘
                              │
                      ┌───────▼───────┐
                      │ models/       │
                      │ ORM Models    │
                      └───────┬───────┘
                              │
                      ┌───────▼───────┐
                      │ core/         │
                      │ Config, DB,   │
                      │ Security,     │
                      │ KubeVirt      │
                      └───────────────┘
```

---

## 📄 `main.py` — Application Entry Point

The FastAPI application instance is created in `main.py`. It configures:

| Aspect | Detail |
|--------|--------|
| **CORS** | Configurable origins via `BACKEND_CORS_ORIGINS` env variable |
| **Routers** | 7 API v1 routers mounted under `/api/v1` |
| **Documentation** | Swagger UI at `/docs`, ReDoc at `/redoc` |
| **Startup** | Database initialization on application startup |
| **Exception Handling** | Global handler with debug/production mode toggle |
| **Health Check** | `GET /health` endpoint for monitoring |

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

---

## 📂 Sub-Packages

| Package | Purpose | Documentation |
|---------|---------|---------------|
| [`api/`](api/README.md) | HTTP layer — route handlers and dependency injection | API layer docs |
| [`core/`](core/README.md) | Config, database, security, KubeVirt client | Core module docs |
| [`models/`](models/README.md) | SQLAlchemy ORM model definitions | Models reference |
| [`schemas/`](schemas/README.md) | Pydantic request/response schemas | Schemas reference |
| [`crud/`](crud/README.md) | Database CRUD operations | CRUD reference |
| [`services/`](services/README.md) | Business logic (discovery, analysis) | Services docs |

