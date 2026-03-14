# 🤝 Contributing to ShiftWise

Thank you for considering contributing to ShiftWise! This document provides guidelines and information to help you get started.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Project Architecture](#project-architecture)

---

## Code of Conduct

This project follows a professional and respectful collaboration standard. All contributors are expected to maintain a constructive and inclusive environment.

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version | Required For |
|------|---------|-------------|
| Python | 3.11+ | Backend development |
| PostgreSQL | 16+ | Database |
| Node.js | 20+ | Frontend development |
| Git | 2.40+ | Version control |

### Setting Up the Development Environment

```bash
# 1. Fork & clone the repository
git clone https://github.com/<your-username>/ShiftWise.git
cd ShiftWise

# 2. Backend setup
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your local database credentials

# 3. Initialize database
python init_db.py

# 4. Frontend setup (separate terminal)
cd ../frontend
npm install
```

### Running the Application Locally

```bash
# Backend (from backend/)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (from frontend/)
npm run dev
```

---

## 🔄 Development Workflow

1. **Create a branch** from `main` with a descriptive name:
   ```bash
   git checkout -b feature/discovery-vmware
   git checkout -b fix/jwt-refresh-expiry
   git checkout -b docs/api-reference-update
   ```

2. **Make your changes** following the [coding standards](#coding-standards).

3. **Run tests** to ensure nothing is broken:
   ```bash
   cd backend
   pytest tests/ -v
   ```

4. **Commit** using the [conventional commit format](#commit-convention).

5. **Push** and open a Pull Request.

---

## 📏 Coding Standards

### Python (Backend)

| Aspect | Standard |
|--------|----------|
| Formatter | `black` (line length: 88) |
| Linter | `flake8` |
| Type checker | `mypy` |
| Docstrings | Google style |
| Naming | `snake_case` for functions/variables, `PascalCase` for classes |

```bash
# Format code
black app/ tests/

# Lint
flake8 app/ tests/

# Type check
mypy app/
```

### TypeScript (Frontend)

| Aspect | Standard |
|--------|----------|
| Linter | ESLint with React Hooks plugin |
| Framework | React 19 with TypeScript strict mode |
| Styling | Tailwind CSS |

```bash
# Lint
npm run lint
```

### General Rules

- Write meaningful docstrings for all public functions and classes
- Keep functions focused — one function, one responsibility
- Use type hints everywhere (Python) and strict TypeScript types
- No hardcoded secrets or credentials — use environment variables via `.env`
- All database schema changes must go through Alembic migrations

---

## 📝 Commit Convention

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>

[optional body]
[optional footer]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation changes |
| `style` | Code formatting (no logic change) |
| `refactor` | Code restructuring (no feature/fix) |
| `test` | Adding or updating tests |
| `chore` | Build scripts, CI, dependencies |
| `perf` | Performance improvement |

### Scopes

`auth`, `users`, `roles`, `vms`, `hypervisors`, `migrations`, `kubevirt`, `discovery`, `analyzer`, `converter`, `migrator`, `frontend`, `infra`, `ci`

### Examples

```
feat(discovery): add VMware vSphere connection handler
fix(auth): correct refresh token expiry timezone handling
docs(api): update KubeVirt endpoint documentation
test(users): add multi-tenancy isolation test cases
```

---

## 🔍 Pull Request Process

1. **Title** must follow the commit convention format
2. **Description** must include:
   - What the PR does (summary)
   - How to test the changes
   - Related issue number (if applicable)
3. **Tests** — all existing tests must pass, new features must include tests
4. **SonarQube** — code must pass quality gate (no new bugs, no security hotspots)
5. **Review** — at least one approval required before merge

### PR Template

```markdown
## Summary
Brief description of the change.

## Type of Change
- [ ] New feature
- [ ] Bug fix
- [ ] Documentation
- [ ] Refactoring

## How to Test
Steps to verify the change locally.

## Checklist
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Linting passes (`black --check app/`)
- [ ] No new SonarQube issues
- [ ] Documentation updated if needed
```

---

## 🏗 Project Architecture

When contributing, understand the layered architecture:

```
API Router (v1/*.py)           ← HTTP layer, request validation
    ↓
Dependencies (deps.py)         ← Authentication, DB sessions
    ↓
CRUD Layer (crud/*.py)         ← Database operations
    ↓
Models (models/*.py)           ← SQLAlchemy ORM definitions
    ↓
Schemas (schemas/*.py)         ← Pydantic request/response schemas
    ↓
Services (services/*.py)       ← Business logic (discovery, analysis)
    ↓
Core (core/*.py)               ← Config, security, KubeVirt client
```

### Key Design Decisions

- **Multi-tenancy** is enforced at the CRUD layer — all queries are tenant-scoped
- **RBAC** is enforced at the dependency injection layer via `deps.py`
- **KubeVirt operations** go through `kubevirt_client.py` which abstracts 3 connection modes
- **Database models** follow an import order in `models/__init__.py` to satisfy SQLAlchemy relationships

---

*Thank you for contributing to ShiftWise! 🚀*