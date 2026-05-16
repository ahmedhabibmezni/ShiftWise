# 📋 Changelog

All notable changes to the ShiftWise project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Work completed on the development branch since v1.0.0 — not yet part of a tagged release.

### ✨ Added

- **Discovery Service** — real VM discovery connectors: VMware Workstation (`vmrun` + VMX scan), Hyper-V (PowerShell over SSH), libvirt/KVM (paramiko SSH + `virsh`), Proxmox VE (REST API), oVirt/RHV (engine SDK). vSphere remains a stub — no test environment available.
- **Analyzer Module** — hybrid compatibility scoring: rule-based feature extraction feeding a scikit-learn classifier; 0–100% score from `predict_proba()`; analyze endpoints under `/api/v1/vms`.
- **Converter Module** — disk format conversion (VMDK/VHD → QCOW2) via `qemu-img` Kubernetes Jobs on an NFS transit zone; `/api/v1/conversions` router for job tracking.
- **Adapter Module** — guest-OS fixup via libguestfs/`virt-customize`: multi-stack DHCP configuration, serial-console enablement, SELinux relabel. Runs as a Kubernetes Job between the Converter and Migrator stages.
- **Migrator Module** — PVC populate (NFS-direct `qemu-img` Job) and KubeVirt VirtualMachine creation, start, and verification; tenant namespace auto-creation; opt-in per-tenant ResourceQuota.
- **Celery + Redis orchestration** — asynchronous, durable migration pipeline wired to `POST /api/v1/migrations/{id}/start`.
- **OpenShift deployment** — `backend/openshift/` manifests (PostgreSQL, Redis, transit PVC, backend, Celery workers, Flower, RBAC, SCC) and a one-command idempotent `deploy.sh`.
- **Frontend SPA** *(in progress)* — React 19 + Vite + TypeScript + Tailwind; login, dashboard, hypervisors, VMs, migrations, reports, users, roles, and settings pages.
- Login audit trail — `last_login_at` and `last_login_ip` recorded on every successful authentication.

### 🔄 Changed

- Access token expiry reduced from 30 to 15 minutes.
- Refresh tokens are now `HttpOnly` cookies backed by Redis, with family-based rotation and reuse detection (a replayed token revokes the whole family).
- CORS hardened — explicit origin / method / header allowlists with `allow_credentials=True`.
- Application lifecycle migrated from `@app.on_event` handlers to the FastAPI `lifespan` context manager.
- `GET /health` now probes PostgreSQL and the auth Redis, reporting `healthy` / `degraded` / `unhealthy`.

### 🔒 Security

- Brute-force protection on `/auth/login` — sliding-window throttle, per email and per source IP.

### 🚧 In Development

- **Frontend SPA** — remaining integration and polish work.
- **Reporting** — dedicated migration-events audit-log table and PDF export.
- **Windows guest support** — `virt-v2v --in-place` path in the Adapter for Windows guests.
- **CI/CD pipeline** — GitHub Actions (lint, pytest, SonarQube, container image build/push).

---

## [1.0.0] — 2026-03-14

### ✨ Added

#### User Management
- Full CRUD operations for user accounts
- Multi-tenancy support with complete data isolation between organizations
- Tenant-scoped queries enforced at the CRUD layer

#### RBAC System
- Role-based access control with 4 predefined system roles:
  - `super_admin` — unrestricted platform access
  - `admin` — full tenant management (users, VMs, migrations)
  - `user` — read/write access to VMs and migrations
  - `viewer` — read-only access
- JSON-based permission matrix stored per role (`{resource: [actions]}`)
- Support for custom roles alongside system roles
- Permission enforcement via dependency injection (`deps.py`)

#### Authentication
- JWT-based authentication with access and refresh tokens
- Access token expiry: 30 minutes (configurable)
- Refresh token expiry: 7 days (configurable)
- Password hashing via bcrypt with 72-byte truncation safety
- Password strength validation (min 8 chars, mixed case + digits)

#### KubeVirt Client
- Kubernetes/OpenShift integration via `python-kubernetes`
- Three connection modes:
  - `kubeconfig` — local development using kubeconfig file
  - `incluster` — production pods using ServiceAccount
  - `custom` — external access with API URL + bearer token
- VM lifecycle operations against KubeVirt API

#### Database & Models
- PostgreSQL as primary data store
- SQLAlchemy 2.0 ORM (synchronous)
- Alembic for schema migrations
- Models: `User`, `Role`, `Hypervisor`, `VirtualMachine`, `Migration`
- Abstract `BaseModel` with integer auto-increment primary keys and audit timestamps

#### API Endpoints
- RESTful API v1 with 7 router groups
- Auto-generated Swagger UI (`/docs`) and ReDoc (`/redoc`)
- Global exception handler with debug mode support
- CORS middleware with configurable allowed origins
- Health check endpoint (`/health`)

#### Testing
- Comprehensive test suite covering all API endpoints
- Tests for user management, RBAC, KubeVirt client, and discovery service

#### Infrastructure
- OpenShift 4.18.1 compact cluster (3 control-plane/worker nodes, bare metal UPI)
- Bastion node with DNS (BIND), HAProxy, Apache HTTP, Chrony (NTP)
- NFS server with `nfs-client` StorageClass
- KubeVirt v1.4.1 installed with `virtctl`
- Domain: `migration.nextstep-it.com`

---

[Unreleased]: https://github.com/didaa16/ShiftWise/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/didaa16/ShiftWise/releases/tag/v1.0.0
