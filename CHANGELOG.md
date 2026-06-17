# 📋 Changelog

All notable changes to the ShiftWise project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Work completed on the development branch since v1.0.0 — not yet part of a tagged release.

### ✨ Added

- **Discovery Service** — real VM discovery connectors: VMware Workstation (`vmrun` + VMX scan), vSphere/ESXi (`pyVmomi` `SmartConnect`), Hyper-V (PowerShell over SSH), libvirt/KVM (paramiko SSH + `virsh`), Proxmox VE (REST API), oVirt/RHV (engine SDK), and physical Linux (P2V) over SSH.
- **Physical server (P2V) source** — migrate a bare-metal Linux host (no hypervisor, no disk image) to OpenShift Virtualization. New `HypervisorType.PHYSICAL` (migration `d1f8274d5e22`); SSH discovery collecting host facts + an `lsblk` block-device plan; a `PhysicalPuller` converter connector that captures each device as a `dd | gzip` raw stream over SSH; an adapter branch that regenerates the guest initramfs with virtio drivers (a bare-metal initramfs has none and would panic on KubeVirt's virtio bus).
- **Real vSphere/ESXi connector** — replaced the previous fake-data vSphere stub with a `pyVmomi` `SmartConnect` implementation working against standalone ESXi (discovery + test-connection + disk conversion; `VMWARE_ESXi` routed through the same connector).
- **Analyzer Module** — hybrid compatibility scoring: rule-based feature extraction feeding a scikit-learn classifier; **intervention-based 0–100 score** (`100 − Σ penalties`, each failing rule weighted by the pipeline work it implies); analyze endpoints under `/api/v1/vms`.
- **Auto migration-strategy selection** — `services/strategy.py:recommend_strategy` maps the compatibility score to a `MigrationStrategy` band (≥90 `DIRECT`, ≥70 `CONVERSION`, ≥50 `HYBRID`, else `COLD`); persisted as `recommended_strategy` and applied automatically when a migration is created (fallback `AUTO`).
- **Converter Module** — disk format conversion (VMDK/VHD/raw → QCOW2) via `qemu-img` Kubernetes Jobs on an NFS transit zone; `/api/v1/conversions` router for job tracking.
- **Adapter Module** — guest-OS fixup via libguestfs/`virt-customize`: multi-stack DHCP configuration, serial-console enablement, SELinux relabel, and P2V virtio-initramfs regeneration. Runs as a Kubernetes Job between the Converter and Migrator stages.
- **Migrator Module** — PVC populate (NFS-direct `qemu-img` Job) and KubeVirt VirtualMachine creation, start, and verification; tenant namespace auto-creation; opt-in per-tenant ResourceQuota.
- **Celery + Redis orchestration** — asynchronous, durable migration pipeline wired to `POST /api/v1/migrations/{id}/start`.
- **OpenShift deployment** — `backend/openshift/` manifests (PostgreSQL, Redis, transit PVC, backend, Celery workers, Flower, RBAC, SCC) and a one-command idempotent `deploy.sh`.
- **Frontend SPA** *(in progress)* — React 19 + Vite + TypeScript + Tailwind; login, dashboard, hypervisors, VMs, migrations, reports, users, roles, settings, and infrastructure pages.
- **Cluster Connectivity Management (feature 002)** — DB-backed per-tenant cluster connection configuration replacing the static `scp kubeconfig` + restart workflow. New Administration **Infrastructure** page (`/api/v1/infrastructure`) lets a superadmin (or a tenant admin scoped to their own tenant) choose the connection mode (`kubeconfig` / `incluster` / `custom`), upload a kubeconfig, run a bounded live connection test, and view cluster details — without a backend restart. Adds the `cluster_connection_config` and append-only `cluster_config_events` tables (migration `f2a7c4e9b1d3`), an effective-config resolver caching one client per `(scope_key, config_version)`, and the `infrastructure` RBAC resource. The `KUBERNETES_*` env vars become a bootstrap fallback seeded into the platform-default scope.
- Login audit trail — `last_login_at` and `last_login_ip` recorded on every successful authentication.

### 🔄 Changed

- Access token expiry reduced from 30 to 15 minutes.
- Refresh tokens are now `HttpOnly` cookies backed by Redis, with family-based rotation and reuse detection (a replayed token revokes the whole family).
- CORS hardened — explicit origin / method / header allowlists with `allow_credentials=True`.
- Application lifecycle migrated from `@app.on_event` handlers to the FastAPI `lifespan` context manager.
- `GET /health` now probes PostgreSQL and the auth Redis, reporting `healthy` / `degraded` / `unhealthy`.

### 🔒 Security

- Brute-force protection on `/auth/login` — sliding-window throttle, per email and per source IP.
- **Cluster credential encryption** — uploaded kubeconfig contents and custom bearer tokens (feature 002) are Fernet-encrypted at rest via the existing credential vault; read schemas are secret-free (`has_credentials: bool`). Custom `api_url` and kubeconfig `cluster.server` URLs are SSRF-validated, and every config change is recorded in the append-only `cluster_config_events` audit table.

### 🐛 Fixed

- **Proxmox disk enumeration** — the converter matched config keys by prefix, so the `scsihw` controller (`virtio-scsi-single`) and `virtiofs0` were parsed as disks, spawning a phantom disk that failed every Proxmox migration with `ERR_DISK_NOT_FOUND`. Now matched by a bus+index pattern (`scsi0`, `virtio1`, …).
- **`DELETE /migrations/{id}` returned HTTP 500** when audit events referenced the migration — the ORM tried to nullify the NOT-NULL `migration_events.migration_id` and hit the append-only trigger. Now returns a clean **409** (audit retention; the trail is preserved); a migration with no events still deletes (204).
- **System-role permissions not reconciled** — `create_system_roles` only created roles when absent, so deployments seeded before the permission-matrix update kept stale grants (`user`/`viewer` could not read hypervisors). It now reconciles `permissions` for existing system roles on startup.
- **Adapter Job created before the tenant namespace existed** (404) — the orchestrator now ensures the tenant namespace before the Adapter stage (idempotent).
- **Adapter pod rejected by SCC** — the `nfs`-volume `shiftwise-populator` SCC was bound only to the control-plane SA; tenant namespaces now get a dedicated `shiftwise-populator` SA + SCC grant provisioned automatically.
- **Adapter `guestfs_launch failed`** — the libguestfs appliance could not start on the nodes; the fixup now forces the TCG software-emulation backend, requires a privileged pod, and makes the staged qcow2 writable for the arbitrary OpenShift UID.
- **Fresh-database initialization failed on PostgreSQL** — boolean columns (`roles.is_system_role`/`is_active`, `users.is_active`/`is_verified`/`is_superuser`) carried an integer `server_default` (`text("0"|"1")`), rendering `BOOLEAN DEFAULT 0` — accepted by SQLite but rejected by PostgreSQL (`DatatypeMismatch`). This broke `Base.metadata.create_all()` and therefore `bootstrap.py` / the `db-init` Job on a brand-new database. Now uses dialect-correct `false()` / `true()`; covered by a PostgreSQL-dialect DDL guard test.
- **Infrastructure page (feature 002 UI)** — the cluster health badge rendered no reason (a `degraded` / `unreachable` / `auth_failed` verdict gave no diagnostic), and the scope editor had no error state (a 403/5xx rendered a blank panel) and used a bare text loader. Now shows `health_reason` with a tooltip, an error callout on load failure, and a skeleton loader — consistent with the rest of the SPA.

### 🧪 Dev / Demo

- **Convert-on-source SFTP transit bridge** (`CONVERTER_SOURCE_CONVERT_SFTP`, default **off**) — for local development where the worker can reach the source hypervisor but not the cluster NFS: converts and compresses the disk on the source node, then uploads the small qcow2 to the transit NFS over SSH (optionally via a bastion jump). The production in-cluster conversion path is unchanged.

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
