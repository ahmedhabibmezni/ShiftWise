<div align="center">

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

**ShiftWise** is an intelligent platform that automates the migration of virtual machines from heterogeneous hypervisor environments (VMware vSphere, libvirt/KVM, Hyper-V) to **Red Hat OpenShift Virtualization**. It combines automated discovery, AI-driven compatibility analysis, disk format conversion, and orchestrated migration execution into a single, unified workflow.

The platform addresses the critical challenges organizations face when modernizing legacy VM workloads: migration failures, excessive manual intervention, and prolonged downtime windows.

### How It Works

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  DISCOVERY   │────▶│   ANALYZER   │────▶│  CONVERTER   │────▶│   MIGRATOR   │────▶│  REPORTING   │
│              │     │              │     │              │     │              │     │              │
│ Auto-detect  │     │ Compatibility│     │ VMDK/VHD →   │     │ Strategy     │     │ Real-time    │
│ VMs from     │     │ check with   │     │ QCOW2 via    │     │ selection &  │     │ dashboards & │
│ hypervisors  │     │ OpenShift    │     │ qemu-img     │     │ orchestrated │     │ migration    │
│              │     │ Virtualization│    │              │     │ execution    │     │ logs         │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

---

## 🎯 Key Objectives

| Objective | Description |
|-----------|-------------|
| **Reduce Migration Failures** | AI-driven compatibility analysis pre-validates VM configurations before migration |
| **Minimize Downtime** | Intelligent strategy selection (cold, warm, live) based on workload characteristics |
| **Eliminate Manual Effort** | Automated disk conversion, config adaptation, and orchestration via Celery |
| **Ensure Compatibility** | Seamless integration with Red Hat OpenShift Virtualization and KubeVirt |
| **Multi-Hypervisor Support** | Unified discovery across VMware vSphere, libvirt/KVM, and Hyper-V |

---

## 🏗 Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │               FRONTEND (React SPA)               │
                    │  Dashboard · Migration Wizard · Compatibility    │
                    │  Reports · Real-time Logs (WebSocket)            │
                    └──────────────────────┬───────────────────────────┘
                                           │ HTTPS / WSS
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
              │  (Persistent  │ │  (Cache/ │ │(Task  │ │  Cluster    │
              │   Storage)    │ │  Broker) │ │Queue) │ │  (KubeVirt) │
              └───────────────┘ └──────────┘ └───────┘ └─────────────┘
```

### Component Responsibilities

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Frontend** | React SPA | Dashboard, migration wizard, real-time monitoring |
| **API** | FastAPI | RESTful endpoints, JWT auth, RBAC enforcement |
| **Services** | Discovery | Auto-detect VMs from connected hypervisors |
| **Services** | Analyzer | Compatibility validation against OpenShift Virtualization |
| **Services** | Converter | Disk format conversion (VMDK/VHD → QCOW2) |
| **Services** | Migrator | Strategy selection and orchestrated migration execution |
| **Data** | PostgreSQL | Persistent storage for users, VMs, migrations, hypervisors |
| **Data** | Redis | Task broker for Celery, caching layer |
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
| Redis | — | Task broker and caching |
| Celery | — | Distributed task queue |
| python-jose | 3.3.0 | JWT token handling |
| passlib + bcrypt | 1.7.4 / 4.0.1 | Password hashing |
| pydantic-settings | 2.1.0 | Configuration management |
| kubernetes | 28.1.0 | Kubernetes/OpenShift API client |
| pyvmomi | 8.0.1 | VMware vSphere SDK |
| paramiko | 3.4.0 | SSH remote operations |

</details>

<details>
<summary><strong>Frontend (Planned)</strong></summary>

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.2 | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 7.2 | Build tool |
| Tailwind CSS | 4.1 | Utility-first CSS |
| TanStack Query | 5.x | Server state management |
| TanStack Table | 8.x | Data tables |
| Zustand | 5.x | Client state management |
| Recharts | 3.x | Data visualization |
| Socket.IO Client | 4.x | Real-time WebSocket communication |
| React Hook Form + Zod | — | Form validation |

</details>

<details>
<summary><strong>Infrastructure</strong></summary>

| Technology | Version | Purpose |
|------------|---------|---------|
| OpenShift | 4.18.1 | Container orchestration platform |
| KubeVirt | 1.4.1 | VM management on Kubernetes |
| RHCOS | 4.18 | Node operating system |
| NFS | — | Default StorageClass (`nfs-client`) |
| HAProxy | — | Load balancer (bastion) |
| BIND (named) | — | DNS server (bastion) |
| Chrony | — | NTP time synchronization |

</details>

<details>
<summary><strong>AI/ML & Tooling</strong></summary>

| Technology | Purpose |
|------------|---------|
| scikit-learn | Classification models for compatibility analysis |
| NumPy / pandas | Data processing and feature engineering |
| libguestfs | Guest filesystem inspection |
| QEMU / qemu-img | Disk format conversion (VMDK/VHD → QCOW2) |
| SonarQube | Code quality and security analysis |

</details>

---

## 📁 Project Structure

```
ShiftWise/
├── backend/                    # FastAPI backend application
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py         # Dependency injection (auth, DB sessions)
│   │   │   └── v1/             # API v1 routers
│   │   │       ├── auth.py     # Authentication endpoints
│   │   │       ├── users.py    # User management endpoints
│   │   │       ├── roles.py    # Role management endpoints
│   │   │       ├── vms.py      # Virtual machine endpoints
│   │   │       ├── hypervisors.py  # Hypervisor endpoints
│   │   │       ├── migrations.py   # Migration endpoints
│   │   │       └── kubevirt.py     # KubeVirt/OpenShift endpoints
│   │   ├── core/
│   │   │   ├── config.py       # Pydantic Settings configuration
│   │   │   ├── database.py     # SQLAlchemy engine & session
│   │   │   ├── security.py     # JWT & password hashing (bcrypt)
│   │   │   └── kubevirt_client.py  # Kubernetes/KubeVirt client
│   │   ├── models/             # SQLAlchemy ORM models
│   │   │   ├── base.py         # Abstract base model (UUID, timestamps)
│   │   │   ├── user.py         # User model with multi-tenancy
│   │   │   ├── role.py         # RBAC roles & permission matrix
│   │   │   ├── hypervisor.py   # Hypervisor connection model
│   │   │   ├── virtual_machine.py  # VM model with compatibility status
│   │   │   └── migration.py    # Migration model with strategy enum
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── crud/               # Database CRUD operations
│   │   └── services/           # Business logic services
│   │       └── discovery.py    # VM discovery service
│   ├── tests/                  # Test suite
│   ├── alembic/                # Database migration scripts
│   ├── config/                 # Configuration files (kubeconfig)
│   ├── requirements.txt        # Python dependencies
│   └── .env.example            # Environment variable template
│
├── frontend/                   # React SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── App.tsx             # Root application component
│   │   └── main.tsx            # Entry point
│   ├── package.json
│   └── vite.config.ts
│
├── infrastructure/             # Infrastructure configuration
│   ├── chrony/                 # NTP synchronization config
│   ├── dns/                    # BIND DNS zone files
│   ├── haproxy/                # Load balancer configuration
│   ├── httpd/                  # Apache HTTP server config
│   └── openshift/              # OpenShift cluster manifests
│
├── docs/                       # Project documentation
│   ├── architecture.md         # Detailed architecture document
│   ├── api-reference.md        # API endpoint reference
│   ├── deployment.md           # Deployment guide
│   └── development.md          # Developer setup guide
│
├── LICENSE                     # MIT License
├── CONTRIBUTING.md             # Contribution guidelines
├── CHANGELOG.md                # Release history
└── SECURITY.md                 # Security policy
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Node.js 20+ (for frontend)
- Access to an OpenShift 4.18 cluster with KubeVirt (for full functionality)

### Backend Setup

```bash
# Clone the repository
git clone https://github.com/ahmedhabibmezni/ShiftWise.git
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

# Initialize the database
python init_db.py

# Run the development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
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

# Expected response:
# {"status": "healthy", "app": "ShiftWise", "version": "1.0.0"}
```

📖 **API Documentation** available at: `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc)

---

## 📊 Module Status

| Module | Status | Description |
|--------|--------|-------------|
| **User Management** | ✅ Complete | Full CRUD with multi-tenancy, tenant isolation |
| **RBAC System** | ✅ Complete | 4 roles (`super_admin`, `admin`, `user`, `viewer`) with permission matrix |
| **Authentication** | ✅ Complete | JWT-based with access/refresh tokens, bcrypt password hashing |
| **KubeVirt Client** | ✅ Complete | 3 connection modes: `kubeconfig`, `in-cluster`, `custom` |
| **Database Init** | ✅ Complete | PostgreSQL schema initialization with Alembic migrations |
| **Test Suite** | ✅ Complete | Comprehensive API tests covering all existing endpoints |
| **Discovery** | 🚧 In Development | Auto-discover VMs from VMware vSphere, libvirt/KVM, Hyper-V |
| **Analyzer** | 🚧 In Development | ML-based compatibility classification (compatible / partial / incompatible) |
| **Converter** | 🚧 In Development | Disk conversion (VMDK/VHD → QCOW2 via qemu-img), config remediation |
| **Migrator** | 🚧 In Development | Migration engine with strategy selection, Celery task orchestration |
| **Reporting** | 🚧 In Development | Real-time migration status, journaling, dashboard data |
| **Frontend** | 🚧 In Development | React SPA with real-time dashboard, migration wizard, WebSocket logs |

---

## 📡 API Reference

### Base URL

```
http://localhost:8000/api/v1
```

### Authentication

All protected endpoints require a JWT Bearer token:

```http
Authorization: Bearer <access_token>
```

### Endpoint Groups

| Prefix | Tag | Description |
|--------|-----|-------------|
| `/api/v1/auth` | Authentication | Login, token refresh, current user |
| `/api/v1/users` | Users | User CRUD with multi-tenancy |
| `/api/v1/roles` | Roles | Role management (system + custom) |
| `/api/v1/vms` | VirtualMachines | VM inventory and compatibility data |
| `/api/v1/hypervisors` | Hypervisors | Hypervisor connection management |
| `/api/v1/migrations` | Migrations | Migration lifecycle management |
| `/api/v1/kubevirt` | KubeVirt / OpenShift | Direct KubeVirt cluster operations |

### RBAC Permission Matrix

| Resource | super_admin | admin | user | viewer |
|----------|:-----------:|:-----:|:----:|:------:|
| Users | `*` (all) | read, create, update | — | — |
| Roles | `*` (all) | read | — | — |
| Hypervisors | `*` (all) | `*` (all) | — | — |
| VMs | `*` (all) | `*` (all) | read, create, update | read |
| Migrations | `*` (all) | `*` (all) | read, create | read |
| Reports | `*` (all) | `*` (all) | read | read |
| Settings | `*` (all) | — | — | — |

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
│  │  10.9.21.150     │    │   (3 nodes: master + worker)         │ │
│  │  RHEL 9.6        │    │                                      │ │
│  │                  │    │  ┌────────────┐  ┌────────────┐      │ │
│  │  Services:       │    │  │ master-0   │  │ master-1   │      │ │
│  │  • DNS (BIND)    │    │  │ 10.9.21.151│  │ 10.9.21.152│      │ │
│  │  • HAProxy       │    │  │ RHCOS 4.18 │  │ RHCOS 4.18 │      │ │
│  │  • HTTP (Apache) │    │  └────────────┘  └────────────┘      │ │
│  │  • NTP (Chrony)  │    │  ┌────────────┐                      │ │
│  └──────────────────┘    │  │ master-2   │  KubeVirt v1.4.1     │ │
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

- **Authentication:** JWT tokens with configurable expiration (access: 30min, refresh: 7 days)
- **Password Storage:** bcrypt hashing with automatic truncation at 72-byte limit
- **RBAC:** Role-based access control with 4 predefined roles and granular permission matrix
- **Multi-Tenancy:** Complete data isolation between tenant organizations
- **CORS:** Configurable allowed origins
- **Kubernetes Auth:** Supports `kubeconfig`, `in-cluster` ServiceAccount, and custom token modes

📖 Security policy: [`SECURITY.md`](SECURITY.md)

---

## 🧪 Testing

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_complete_api.py -v          # Full API test suite
pytest tests/test_user_management.py -v       # User management tests
pytest tests/test_kubevirt_client.py -v        # KubeVirt client tests
pytest tests/test_discovery.py -v             # Discovery service tests
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