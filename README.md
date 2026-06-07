<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="frontend/public/Horizontal_Dark_Mode.png">
  <source media="(prefers-color-scheme: light)" srcset="frontend/public/Horizontal_Light_Mode.png">
  <img src="frontend/public/Horizontal_Light_Mode.png" alt="ShiftWise" width="420">
</picture>

# 🔄 ShiftWise

### Intelligent VM-to-OpenShift Migration Platform

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![OpenShift](https://img.shields.io/badge/OpenShift-4.18-EE0000?style=for-the-badge&logo=redhatopenshift&logoColor=white)](https://www.redhat.com/en/technologies/cloud-computing/openshift)
[![KubeVirt](https://img.shields.io/badge/KubeVirt-1.4.1-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white)](https://kubevirt.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![SonarQube](https://img.shields.io/badge/SonarQube-Quality%20Gate-4E9BCD?style=for-the-badge&logo=sonarqube&logoColor=white)](https://www.sonarqube.org)

*5th-Year Engineering Internship Project — Architecture IT & Cloud Computing*

**Author:** Ahmed Habib Mezni · **Supervisor:** NextStep IT

---

[Architecture](#-architecture) · [Tech Stack](#-tech-stack) · [Quick Start](#-quick-start) · [API Reference](#-api-reference) · [Infrastructure](#-infrastructure) · [Contributing](#-contributing)

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Objectives](#-key-objectives)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Module Status](#-module-status)
- [API Reference](#-api-reference)
- [Infrastructure](#-infrastructure)
- [Security](#-security)
- [Testing](#-testing)
- [License](#-license)

---

## 🎯 Overview

**ShiftWise** is an intelligent platform that automates the migration of virtual machines from heterogeneous hypervisor environments (VMware vSphere, VMware Workstation, libvirt/KVM, Microsoft Hyper-V, Proxmox VE, oVirt/RHV) to **Red Hat OpenShift Virtualization**. It combines automated discovery, AI-driven compatibility analysis, disk format conversion, guest-OS adaptation, and orchestrated migration execution into a single, unified workflow.

The platform addresses the critical challenges organizations face when modernizing legacy VM workloads: migration failures, excessive manual intervention, and prolonged downtime windows.

### How It Works

```
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│ DISCOVERY  │─▶│  ANALYZER  │─▶│ CONVERTER  │─▶│  ADAPTER   │─▶│  MIGRATOR  │─▶│ REPORTING  │
│            │  │            │  │            │  │            │  │            │  │            │
│ Auto-      │  │ Hybrid     │  │ VMDK/VHD → │  │ Guest-OS   │  │ PVC        │  │ Status,    │
│ detect VMs │  │ rules + ML │  │ QCOW2 via  │  │ fixup via  │  │ populate + │  │ history &  │
│ from 6     │  │ compat.    │  │ qemu-img   │  │ libguestfs │  │ KubeVirt   │  │ CSV        │
│ hypervisor │  │ scoring    │  │ K8s Jobs   │  │ (DHCP,     │  │ VM create  │  │ export     │
│ types      │  │ (0–100%)   │  │            │  │ console)   │  │ & verify   │  │            │
└────────────┘  └────────────┘  └────────────┘  └────────────┘  └────────────┘  └────────────┘
```

The pipeline is orchestrated asynchronously by Celery workers backed by Redis.

---

## 🎯 Key Objectives

| Objective | Description |
|-----------|-------------|
| **Reduce Migration Failures** | AI-driven compatibility analysis pre-validates VM configurations before migration |
| **Minimize Downtime** | Strategy selection (direct, conversion, cold, warm, hybrid, auto) based on workload characteristics |
| **Eliminate Manual Effort** | Automated disk conversion, guest-OS adaptation, and orchestration via Celery |
| **Ensure Compatibility** | Guest-OS fixup (multi-stack DHCP, serial console, SELinux relabel) so migrated VMs boot correctly on KubeVirt |
| **Multi-Hypervisor Support** | Unified discovery across VMware vSphere/Workstation, libvirt/KVM, Hyper-V, Proxmox VE, and oVirt/RHV |

---

## 🏗 Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │               FRONTEND (React SPA)               │
                    │  Dashboard · Migration Wizard · Compatibility    │
                    │  Reports · Real-time Monitoring (polling)        │
                    └──────────────────────┬───────────────────────────┘
                                           │ HTTPS / REST
                    ┌──────────────────────▼───────────────────────────┐
                    │              API GATEWAY (FastAPI)                │
                    │                                                   │
                    │  ┌─────────┐ ┌───────┐ ┌───────┐ ┌────────────┐ │
                    │  │  Auth   │ │ Users │ │ Roles │ │ Hypervisors│ │
                    │  │  (JWT)  │ │ CRUD  │ │ RBAC  │ │   CRUD     │ │
                    │  └─────────┘ └───────┘ └───────┘ └────────────┘ │
                    │  ┌─────────┐ ┌───────┐ ┌───────┐ ┌────────────┐ │
                    │  │   VMs   │ │Migrat.│ │KubeV. │ │ Discovery  │ │
                    │  │  CRUD   │ │Engine │ │Client │ │  Service   │ │
                    │  └─────────┘ └───────┘ └───────┘ └────────────┘ │
                    └──────┬──────────┬──────────┬──────────┬──────────┘
                           │          │          │          │
              ┌────────────▼──┐ ┌─────▼────┐ ┌──▼────┐ ┌──▼──────────┐
              │  PostgreSQL   │ │  Redis   │ │Celery │ │  OpenShift  │
              │  (Persistent  │ │  (Broker │ │(Task  │ │  Cluster    │
              │   Storage)    │ │  + Auth) │ │Queue) │ │  (KubeVirt) │
              └───────────────┘ └──────────┘ └───────┘ └─────────────┘
```

### Component Responsibilities

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Frontend** | React SPA | Dashboard, migration workflow, real-time monitoring |
| **API** | FastAPI | RESTful endpoints, JWT auth, RBAC enforcement, multi-tenancy |
| **Services** | Discovery | Auto-detect VMs from connected hypervisors |
| **Services** | Analyzer | Hybrid rules + ML compatibility scoring against OpenShift Virtualization |
| **Services** | Converter | Disk format conversion (VMDK/VHD → QCOW2) via Kubernetes Jobs |
| **Services** | Adapter | Guest-OS fixup (DHCP, serial console, SELinux relabel) via libguestfs |
| **Services** | Migrator | PVC populate + KubeVirt VirtualMachine creation and verification |
| **Workers** | Celery | Asynchronous, durable migration pipeline execution |
| **Data** | PostgreSQL | Persistent storage for users, VMs, migrations, hypervisors |
| **Data** | Redis | Celery broker/result backend + refresh-token store |
| **Infra** | OpenShift 4.18 | Target platform with KubeVirt v1.4.1 |

---

## 🛠 Tech Stack

<details>
<summary><strong>Backend</strong></summary>

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Core language |
| FastAPI | 0.109.0 | Web framework (async, auto-docs) |
| SQLAlchemy | 2.0.25 | ORM and database abstraction |
| Alembic | 1.13.1 | Database migrations |
| PostgreSQL | 16 | Primary database |
| Redis | 5.0.1 | Celery broker/result backend + refresh-token store |
| Celery | 5.3.6 | Distributed task queue |
| Flower | 2.0.1 | Celery task monitoring UI |
| python-jose | 3.3.0 | JWT token handling |
| passlib + bcrypt | 1.7.4 / 4.0.1 | Password hashing |
| pydantic-settings | 2.1.0 | Configuration management |
| kubernetes | 28.1.0 | Kubernetes/OpenShift API client |
| pyvmomi | 8.0.1 | VMware vSphere SDK |
| libvirt-python | 11.3.0 | libvirt/KVM bindings (Linux) |
| proxmoxer | 2.0.1 | Proxmox VE REST API client |
| ovirt-engine-sdk-python | 4.6.3 | oVirt / RHV engine SDK |
| paramiko | 3.4.0 | SSH remote operations |
| scikit-learn | 1.5.2 | Compatibility classification model |
| NumPy / pandas | 1.26.4 / 2.2.1 | Feature engineering |

</details>

<details>
<summary><strong>Frontend</strong></summary>

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.2 | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 7.2 | Build tool & dev server |
| Tailwind CSS | 4.1 | Utility-first CSS |
| React Router | 7.13 | Client-side routing |
| TanStack Query | 5.x | Server state management (with polling) |
| Zustand | 5.x | Client state management (auth, UI) |
| Axios | 1.13 | HTTP client with JWT refresh interceptor |
| React Hook Form + Zod | 7.x / 4.x | Form handling and validation |
| lucide-react | 0.563 | Icon set |
| react-hot-toast | 2.6 | Toast notifications |
| Vitest + MSW | 4.x / 2.x | Unit testing + API mocking |

</details>

<details>
<summary><strong>Infrastructure</strong></summary>

| Technology | Version | Purpose |
|------------|---------|---------|
| OpenShift | 4.18.1 | Container orchestration platform |
| KubeVirt | 1.4.1 | VM management on Kubernetes |
| RHCOS | 4.18 | Node operating system |
| NFS | — | Default StorageClass (`nfs-client`) + conversion transit zone |
| HAProxy | — | Load balancer (bastion) |
| BIND (named) | — | DNS server (bastion) |
| Chrony | — | NTP time synchronization |

</details>

<details>
<summary><strong>AI/ML & Tooling</strong></summary>

| Technology | Purpose |
|------------|---------|
| scikit-learn | Classification model for compatibility analysis |
| NumPy / pandas | Data processing and feature engineering |
| libguestfs / virt-customize | Guest filesystem inspection and OS fixup |
| QEMU / qemu-img | Disk format conversion (VMDK/VHD → QCOW2) |
| SonarQube | Code quality and security analysis |

</details>

---

## 📁 Project Structure

```
ShiftWise/
├── backend/                      # FastAPI backend application
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py           # Auth, RBAC (check_permission), tenant scoping
│   │   │   └── v1/               # API v1 routers
│   │   │       ├── auth.py       # Login, refresh, logout, change-password
│   │   │       ├── users.py      # User management
│   │   │       ├── roles.py      # Role / RBAC management
│   │   │       ├── vms.py        # VM inventory + analyze + convert
│   │   │       ├── hypervisors.py    # Hypervisor connections + sync
│   │   │       ├── migrations.py     # Migration lifecycle + start/cancel
│   │   │       ├── kubevirt.py       # KubeVirt/OpenShift operations
│   │   │       ├── conversions.py    # Disk conversion tracking
│   │   │       └── infrastructure.py # Per-tenant cluster connection config
│   │   ├── core/
│   │   │   ├── config.py             # Pydantic Settings
│   │   │   ├── database.py           # SQLAlchemy engine & session
│   │   │   ├── security.py           # JWT (HS256) & bcrypt hashing
│   │   │   ├── kubevirt_client.py    # Kubernetes/KubeVirt client
│   │   │   ├── celery_app.py         # Celery application
│   │   │   ├── redis_client.py       # Redis connection (auth store)
│   │   │   ├── refresh_token_store.py    # Refresh-token family rotation
│   │   │   ├── login_throttle.py     # Brute-force protection
│   │   │   └── constants.py          # Shared constants
│   │   ├── models/               # SQLAlchemy ORM models (Integer PK ids)
│   │   │   ├── base.py           # BaseModel (id, created_at, updated_at)
│   │   │   ├── user.py           # User model with multi-tenancy
│   │   │   ├── role.py           # RBAC roles & permission matrix
│   │   │   ├── hypervisor.py     # Hypervisor connection model
│   │   │   ├── virtual_machine.py    # VM model with compatibility status
│   │   │   ├── migration.py      # Migration model with strategy enum
│   │   │   └── conversion.py     # Disk conversion group/job/attempt
│   │   ├── schemas/              # Pydantic v2 request/response schemas
│   │   ├── crud/                 # Database CRUD operations
│   │   ├── services/             # Business logic services
│   │   │   ├── discovery.py      # VM discovery connectors
│   │   │   ├── analyzer.py       # Compatibility analysis
│   │   │   ├── compatibility_rules.py    # Rule-based feature extraction
│   │   │   ├── feature_extractor.py
│   │   │   ├── converter/        # Disk conversion (qemu-img K8s Jobs)
│   │   │   ├── adapter/          # Guest-OS fixup (libguestfs)
│   │   │   ├── migrator/         # PVC populate + KubeVirt VM create
│   │   │   └── cluster/          # Effective-config resolver + client cache + connection probe
│   │   ├── tasks/                # Celery tasks (migration, conversion)
│   │   ├── ml/                   # ML training scripts + model artifacts
│   │   └── main.py               # FastAPI application entry point
│   ├── tests/                    # Test suite (pytest)
│   ├── alembic/                  # Database migration scripts
│   ├── openshift/                # OpenShift manifests + deploy.sh
│   ├── config/                   # Configuration files (kubeconfig)
│   ├── Dockerfile                # Single image: backend/worker/populator/adapter
│   ├── init_db.py                # Database initialization & seeding
│   ├── requirements.txt          # Python dependencies
│   └── .env.example              # Environment variable template
│
├── frontend/                     # React 19 SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── api/                  # Typed API client modules
│   │   ├── app/                  # App layout + auth gate
│   │   ├── components/           # UI component library
│   │   ├── pages/                # Route pages + drawers
│   │   ├── hooks/  lib/  store/  styles/
│   │   ├── routes.tsx            # Router configuration
│   │   └── main.tsx              # Entry point
│   ├── package.json
│   └── vite.config.ts
│
├── infrastructure/               # Infrastructure configuration
│   ├── chrony/                   # NTP synchronization config
│   ├── dns/                      # BIND DNS zone files
│   ├── haproxy/                  # Load balancer configuration
│   ├── httpd/                    # Apache HTTP server config
│   └── openshift/                # OpenShift install-config + health checks
│
├── docs/                         # Project documentation
│   ├── architecture.md           # Detailed architecture document
│   ├── api-reference.md          # API endpoint reference
│   ├── deployment.md             # Deployment guide
│   ├── development.md            # Developer setup guide
│   └── incidents/                # Incident post-mortems
│
├── LICENSE                       # MIT License
├── CONTRIBUTING.md               # Contribution guidelines
├── CHANGELOG.md                  # Release history
└── SECURITY.md                   # Security policy
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Redis 7+ (required for authentication and Celery)
- Node.js 20+ (for frontend)
- Access to an OpenShift 4.18 cluster with KubeVirt (for migration execution)

### Backend Setup

```bash
# Clone the repository
git clone https://github.com/didaa16/ShiftWise.git
cd ShiftWise/backend

# Create and activate virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your database credentials and settings

# Initialize the database (creates tables + 4 system roles)
python init_db.py

# Run the development server
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd ShiftWise/frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Verify Installation

```bash
# Health check
curl http://localhost:8000/health

# Expected response (healthy):
# {
#   "status": "healthy",
#   "app": "ShiftWise",
#   "version": "1.0.0",
#   "checks": {
#     "database":   { "ok": true, "latency_ms": 4, "error": null },
#     "redis_auth": { "ok": true, "latency_ms": 1, "error": null }
#   }
# }
```

📖 **API Documentation** available at: `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc)

---

## 📊 Module Status

| Module | Status | Description |
|--------|--------|-------------|
| **Authentication** | ✅ Complete | JWT (HS256), 15-min access token, HttpOnly-cookie refresh with Redis-backed family rotation, brute-force throttle, login audit trail |
| **User Management** | ✅ Complete | Full CRUD with multi-tenancy and tenant isolation |
| **RBAC System** | ✅ Complete | 4 system roles (`super_admin`, `admin`, `user`, `viewer`) + custom roles, permission matrix |
| **KubeVirt Client** | ✅ Complete | 3 connection modes: `kubeconfig`, `incluster`, `custom` |
| **Cluster Connectivity** | ✅ Complete | DB-backed per-tenant cluster connection config (Infrastructure page) — dynamic kubeconfig upload / mode switch / live test, replacing the static `scp` + restart workflow |
| **Discovery** | ✅ Complete | Real connectors for VMware Workstation, Hyper-V, KVM, Proxmox VE, oVirt/RHV (vSphere: stub) |
| **Analyzer** | ✅ Complete | Hybrid rule engine + scikit-learn classifier, 0–100% compatibility score |
| **Converter** | ✅ Complete | VMDK/VHD → QCOW2 via qemu-img Kubernetes Jobs on NFS transit |
| **Adapter** | ✅ Complete | Guest-OS fixup (multi-stack DHCP, serial console, SELinux relabel) via libguestfs |
| **Migrator** | ✅ Complete | PVC populate (NFS-direct qemu-img Job) + KubeVirt VM create/start/verify |
| **Celery Orchestration** | ✅ Complete | Redis-backed asynchronous migration pipeline |
| **OpenShift Deployment** | ✅ Complete | One-command deploy (`backend/openshift/deploy.sh`) |
| **Test Suite** | ✅ Complete | ~85% coverage across the backend test suite |
| **Frontend** | 🚧 In Progress | React 19 SPA — core pages built (login, dashboard, hypervisors, VMs, migrations, reports, users, roles, settings, infrastructure) |
| **Reporting** | 🚧 In Progress | Stats endpoints + migration-history page with CSV export; dedicated audit-log table pending |

---

## 📡 API Reference

### Base URL

```
http://localhost:8000/api/v1
```

### Authentication

Protected endpoints require a JWT Bearer token:

```http
Authorization: Bearer <access_token>
```

The refresh token is delivered as an `HttpOnly` cookie (not a body field) and is backed by Redis with family-based rotation and reuse detection.

### Endpoint Groups

| Prefix | Tag | Description |
|--------|-----|-------------|
| `/api/v1/auth` | Authentication | Login, token refresh, logout, current user, change password |
| `/api/v1/users` | Users | User CRUD with multi-tenancy |
| `/api/v1/roles` | Roles | Role management (system + custom) |
| `/api/v1/vms` | VirtualMachines | VM inventory, compatibility analysis, conversion trigger |
| `/api/v1/hypervisors` | Hypervisors | Hypervisor connection management + sync |
| `/api/v1/migrations` | Migrations | Migration lifecycle (create, start, cancel) |
| `/api/v1/kubevirt` | KubeVirt / OpenShift | Direct KubeVirt cluster operations |
| `/api/v1/conversions` | Conversions | Disk conversion job tracking |
| `/api/v1/infrastructure` | Infrastructure | Per-tenant cluster connection config (mode, kubeconfig upload, live connection test) |

### RBAC Permission Matrix

| Resource | super_admin | admin | user | viewer |
|----------|:-----------:|:-----:|:----:|:------:|
| Users | `*` (all) | read, create, update | — | — |
| Roles | `*` (all) | read | — | — |
| Hypervisors | `*` (all) | `*` (all) | — | — |
| VMs | `*` (all) | `*` (all) | read, create, update | read |
| Migrations | `*` (all) | `*` (all) | read, create | read |
| Conversions | `*` (all) | `*` (all) | read, create | read |
| Reports | `*` (all) | `*` (all) | read | read |
| Infrastructure | `*` (all) | read, update (own tenant) | — | — |
| Settings | `*` (all) | — | — | — |

Superusers bypass all permission checks. Every non-superuser request is scoped to the user's `tenant_id`.

📖 Full API documentation: [`docs/api-reference.md`](docs/api-reference.md)

---

## 🖥 Infrastructure

### Cluster Topology

```
┌───────────────────────────────────────────────────────────────────┐
│                    Network: 10.9.21.0/24                          │
│                                                                   │
│  ┌──────────────────┐    ┌──────────────────────────────────────┐ │
│  │  BASTION NODE    │    │   OPENSHIFT COMPACT CLUSTER          │ │
│  │  10.9.21.150     │    │   (3 nodes: control-plane + worker)  │ │
│  │  RHEL 9.6        │    │                                      │ │
│  │                  │    │  ┌────────────┐  ┌────────────┐      │ │
│  │  Services:       │    │  │ node01     │  │ node02     │      │ │
│  │  • DNS (BIND)    │    │  │ 10.9.21.151│  │ 10.9.21.152│      │ │
│  │  • HAProxy       │    │  │ RHCOS 4.18 │  │ RHCOS 4.18 │      │ │
│  │  • HTTP (Apache) │    │  └────────────┘  └────────────┘      │ │
│  │  • NTP (Chrony)  │    │  ┌────────────┐                      │ │
│  └──────────────────┘    │  │ node03     │  KubeVirt v1.4.1     │ │
│                          │  │ 10.9.21.153│  virtctl installed   │ │
│  ┌──────────────────┐    │  │ RHCOS 4.18 │                      │ │
│  │  NFS SERVER      │    │  └────────────┘                      │ │
│  │  10.9.21.154     │    └──────────────────────────────────────┘ │
│  │  Ubuntu 24.04    │                                             │
│  │  StorageClass:   │    Domain: migration.nextstep-it.com        │
│  │  nfs-client      │    Console: console-openshift-console.apps  │
│  └──────────────────┘    API: api.migration.nextstep-it.com:6443  │
└───────────────────────────────────────────────────────────────────┘
```

📖 Full infrastructure documentation: [`infrastructure/README.md`](infrastructure/README.md)

---

## 🔒 Security

- **Authentication:** JWT access tokens (HS256), 15-minute expiry; refresh tokens (7 days) issued as `HttpOnly` cookies, Redis-backed with family rotation and reuse detection
- **Brute-force protection:** sliding-window login throttle per email and per source IP
- **Audit trail:** `last_login_at` / `last_login_ip` recorded on every successful login
- **Password Storage:** bcrypt hashing with automatic truncation at the 72-byte limit
- **RBAC:** Role-based access control with 4 predefined roles and a granular permission matrix
- **Multi-Tenancy:** Data isolation between tenant organizations enforced on every query
- **CORS:** Explicit origin / method / header allowlists (no wildcards), `allow_credentials=True`
- **Kubernetes Auth:** Supports `kubeconfig`, `incluster` ServiceAccount, and `custom` token modes
- **Cluster Connection Config:** Per-tenant cluster connectivity is DB-backed; uploaded kubeconfigs and custom bearer tokens are Fernet-encrypted at rest (read schemas are secret-free), SSRF-guarded on custom `api_url`/`cluster.server`, and changes are recorded in an append-only `cluster_config_events` audit table

📖 Security policy: [`SECURITY.md`](SECURITY.md)

---

## 🧪 Testing

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_complete_api.py -v          # Full API test suite
pytest tests/test_user_management.py -v       # User management + RBAC
pytest tests/test_kubevirt_client.py -v       # KubeVirt client modes
pytest tests/test_analyzer.py -v              # Compatibility analyzer
pytest tests/test_migrator.py -v              # Migrator service
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

**Copyright © 2026 Ahmed Habib Mezni — NextStep IT**

---

<div align="center">

**Built with ❤️ for the OpenShift ecosystem**

[⬆ Back to Top](#-shiftwise)

</div>
