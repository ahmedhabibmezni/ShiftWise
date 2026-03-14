# 🛠 ShiftWise Developer Guide

> Everything you need to set up your development environment and contribute to ShiftWise.

---

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Setup](#-environment-setup)
- [Project Architecture](#-project-architecture)
- [Development Workflow](#-development-workflow)
- [Backend Development](#-backend-development)
- [Frontend Development](#-frontend-development)
- [Database Management](#-database-management)
- [Testing](#-testing)
- [Code Quality](#-code-quality)
- [Debugging](#-debugging)
- [Common Tasks](#-common-tasks)

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://python.org) |
| PostgreSQL | 16+ | [postgresql.org](https://postgresql.org) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |
| Git | 2.40+ | [git-scm.com](https://git-scm.com) |
| VS Code / PyCharm | Latest | Recommended IDEs |

---

## 🚀 Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/ahmedhabibmezni/ShiftWise.git
cd ShiftWise
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate
.venv\Scripts\activate          # Windows PowerShell
source .venv/bin/activate       # Linux/macOS/WSL

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` with your local settings:

```env
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=shiftwise_db
DATABASE_USER=postgres
DATABASE_PASSWORD=your_password
SECRET_KEY=dev-secret-key-change-in-production
DEBUG=True
LOG_LEVEL=DEBUG
```

### 3. Database Setup

```bash
# Create database (PostgreSQL must be running)
python create_db.py

# Initialize tables and seed data
python init_db.py
```

### 4. Start Backend Server

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The `--reload` flag enables hot-reloading on code changes.

### 5. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

---

## 🏗 Project Architecture

```
ShiftWise/
├── backend/                    # FastAPI REST API
│   ├── app/
│   │   ├── api/v1/             # Route handlers
│   │   ├── core/               # Config, DB, security, KubeVirt
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── crud/               # Database operations
│   │   ├── services/           # Business logic
│   │   └── main.py             # App entry point
│   ├── tests/                  # Test suite
│   └── alembic/                # DB migrations
├── frontend/                   # React SPA
├── infrastructure/             # Cluster configs
└── docs/                       # Documentation
```

### Request Flow

```
Client → Router → Dependencies (auth/RBAC) → CRUD/Service → Model → DB
                                                                   ↓
Client ← Schema (response) ← CRUD/Service ← Model ← DB Response
```

---

## 🔄 Development Workflow

### Branch Naming

```
feature/<module>-<description>     # New features
fix/<module>-<description>         # Bug fixes
docs/<topic>                       # Documentation
refactor/<module>-<description>    # Refactoring
test/<module>-<description>        # Test additions
```

**Examples:**
```bash
git checkout -b feature/discovery-vmware-connector
git checkout -b fix/auth-refresh-token-expiry
git checkout -b docs/api-migration-endpoints
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(discovery): implement VMware vSphere VM enumeration
fix(auth): handle expired refresh tokens gracefully
test(users): add multi-tenancy isolation test cases
docs(api): update KubeVirt endpoint documentation
```

---

## ⚙️ Backend Development

### Adding a New API Endpoint

1. **Define the schema** in `schemas/<resource>.py`:
   ```python
   class NewResourceCreate(BaseModel):
       name: str
       description: str | None = None
   ```

2. **Create/update the model** in `models/<resource>.py`:
   ```python
   class NewResource(BaseModel):
       __tablename__ = "new_resources"
       name = Column(String, nullable=False)
   ```

3. **Add CRUD operations** in `crud/<resource>.py`:
   ```python
   def create(db: Session, obj_in: NewResourceCreate, tenant_id: str):
       db_obj = NewResource(**obj_in.dict(), tenant_id=tenant_id)
       db.add(db_obj)
       db.commit()
       return db_obj
   ```

4. **Create the router** in `api/v1/<resource>.py`:
   ```python
   router = APIRouter()

   @router.post("/", response_model=NewResourceResponse)
   def create_resource(
       obj_in: NewResourceCreate,
       db: Session = Depends(get_db),
       current_user: User = Depends(require_role(["admin"]))
   ):
       return crud.create(db, obj_in, current_user.tenant_id)
   ```

5. **Register the router** in `main.py`:
   ```python
   app.include_router(
       new_resource.router,
       prefix=f"{settings.API_V1_PREFIX}/new-resources",
       tags=["NewResources"]
   )
   ```

6. **Create a migration** for the new model:
   ```bash
   alembic revision --autogenerate -m "add new_resources table"
   alembic upgrade head
   ```

### Adding a New Service

Services go in `services/<name>.py` and contain business logic:

```python
# services/new_service.py
class NewService:
    def __init__(self, db: Session):
        self.db = db

    def process(self, data):
        # Business logic here
        pass
```

---

## 🎨 Frontend Development

### Key Libraries

| Library | Usage |
|---------|-------|
| `@tanstack/react-query` | Server state (API data fetching with caching) |
| `zustand` | Client state (auth tokens, UI state) |
| `react-router-dom` | Routing |
| `react-hook-form` + `zod` | Form handling + validation |
| `axios` | HTTP client |

### Adding a New Page

1. Create the component in `src/pages/NewPage.tsx`
2. Add the route in `src/App.tsx`
3. Create API hooks in `src/hooks/useNewResource.ts`

---

## 🗄 Database Management

### Alembic Commands

```bash
# Generate migration from model changes
alembic revision --autogenerate -m "description"

# Apply all migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# View migration history
alembic history --verbose

# Show current revision
alembic current
```

### Reset Database (Development Only)

```bash
# Drop and recreate
python -c "
from app.core.database import engine, Base
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
print('Database reset complete')
"

# Re-seed
python init_db.py
```

---

## 🧪 Testing

```bash
# Full test suite
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=term --cov-report=html

# Specific file
pytest tests/test_complete_api.py -v

# Specific test
pytest tests/ -v -k "test_create_user"

# Stop on first failure
pytest tests/ -v -x
```

### Writing Tests

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

---

## 📏 Code Quality

### Formatting & Linting

```bash
# Format with Black
black app/ tests/

# Check formatting
black --check app/ tests/

# Lint with Flake8
flake8 app/ tests/

# Type check with mypy
mypy app/
```

### SonarQube

```bash
sonar-scanner \
  -Dsonar.projectKey=shiftwise \
  -Dsonar.sources=backend/app \
  -Dsonar.tests=backend/tests
```

---

## 🔍 Debugging

### FastAPI Debug Mode

Set `DEBUG=True` in `.env` for:
- Auto-reload on code changes
- Detailed error responses with stack traces
- Full exception type and path in error JSON

### Interactive Debugger

```bash
# Run with debugpy (VS Code debugger)
python -m debugpy --listen 5678 -m uvicorn app.main:app --reload
```

### API Testing

- **Swagger UI:** `http://localhost:8000/docs` — interactive API testing
- **ReDoc:** `http://localhost:8000/redoc` — API reference
- **HTTP files:** Use `test_main.http` with VS Code REST Client or IntelliJ

---

## 📝 Common Tasks

<details>
<summary><strong>Generate a SECRET_KEY</strong></summary>

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```
</details>

<details>
<summary><strong>Create a new superadmin user</strong></summary>

```python
python init_db.py
# Or via API:
# POST /api/v1/auth/login → get token
# POST /api/v1/users with super_admin role
```
</details>

<details>
<summary><strong>Test KubeVirt connection</strong></summary>

```python
from app.core.kubevirt_client import get_kubevirt_client

client = get_kubevirt_client()
namespaces = client.list_namespaces()
print(f"Connected! Found {len(namespaces)} namespaces")
```
</details>

<details>
<summary><strong>Check database connection</strong></summary>

```python
from app.core.database import engine

with engine.connect() as conn:
    result = conn.execute("SELECT 1")
    print("Database connected!" if result else "Connection failed")
```
</details>