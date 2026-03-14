# 📋 Changelog

All notable changes to the ShiftWise project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### 🚧 In Development

- **Discovery Module** — Auto-discover VMs from VMware vSphere, libvirt/KVM, and Hyper-V
- **Analyzer Module** — ML-based compatibility classification for OpenShift Virtualization
- **Converter Module** — Automated disk format conversion (VMDK/VHD → QCOW2 via qemu-img)
- **Migrator Module** — Migration engine with strategy selection and Celery orchestration
- **Reporting Module** — Real-time migration status, journaling, and dashboard data
- **Frontend SPA** — React dashboard with migration wizard, WebSocket-based real-time logs

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
  - `in-cluster` — production pods using ServiceAccount
  - `custom` — external access with API URL + bearer token
- VM lifecycle operations against KubeVirt API

#### Database & Models
- PostgreSQL as primary data store
- SQLAlchemy 2.0 ORM with async-ready patterns
- Alembic for schema migrations
- Models: `User`, `Role`, `Hypervisor`, `VirtualMachine`, `Migration`
- Abstract `BaseModel` with UUID primary keys and audit timestamps

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
- OpenShift 4.18.1 compact cluster (3 master/worker nodes, bare metal UPI)
- Bastion node with DNS (BIND), HAProxy, Apache HTTP, Chrony (NTP)
- NFS server with `nfs-client` StorageClass
- KubeVirt v1.4.1 installed with `virtctl`
- Domain: `migration.nextstep-it.com`

---

[Unreleased]: https://github.com/ahmedhabibmezni/ShiftWise/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ahmedhabibmezni/ShiftWise/releases/tag/v1.0.0