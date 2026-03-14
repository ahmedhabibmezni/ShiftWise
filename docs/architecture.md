# 🏗 ShiftWise Architecture

> Detailed architecture document for the ShiftWise intelligent VM-to-OpenShift migration platform.

---

## 📋 Table of Contents

- [System Overview](#system-overview)
- [High-Level Architecture](#high-level-architecture)
- [Data Flow](#data-flow)
- [Backend Architecture](#backend-architecture)
- [Data Model](#data-model)
- [Security Architecture](#security-architecture)
- [Infrastructure Architecture](#infrastructure-architecture)
- [Migration Pipeline](#migration-pipeline)

---

## System Overview

ShiftWise is a full-stack platform that automates the lifecycle of migrating virtual machines from heterogeneous hypervisor environments to Red Hat OpenShift Virtualization. The system is built around five core stages: **Discovery → Analysis → Conversion → Migration → Reporting**.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE                                  │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                     React SPA (Vite + TypeScript)                  │  │
│  │  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐   │  │
│  │  │Dashboard │ │Migration     │ │VM Inventory│ │Compatibility │   │  │
│  │  │Overview  │ │Wizard        │ │Table       │ │Reports       │   │  │
│  │  └──────────┘ └──────────────┘ └────────────┘ └──────────────┘   │  │
│  └──────────────────────────┬─────────────────────────────────────────┘  │
│                              │ REST API + WebSocket                       │
└──────────────────────────────┼───────────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────────────┐
│                         BACKEND SERVICES                                  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │                    FastAPI Application                           │     │
│  │                                                                  │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │     │
│  │  │ Auth     │ │ User     │ │ Role     │ │ KubeVirt Client  │  │     │
│  │  │ (JWT)    │ │ Mgmt     │ │ (RBAC)   │ │ (3 modes)        │  │     │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │     │
│  │  │Discovery │ │Analyzer  │ │Converter │ │ Migrator         │  │     │
│  │  │Service   │ │(ML)      │ │(qemu-img)│ │ (Celery tasks)   │  │     │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                                                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────────────────────┐     │
│  │PostgreSQL│ │ Redis    │ │ Celery Workers                       │     │
│  │(Data)    │ │(Broker)  │ │(Background tasks: conversion/migrate)│     │
│  └──────────┘ └──────────┘ └──────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
                               │
                               │ Kubernetes API
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      OPENSHIFT CLUSTER                                   │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  KubeVirt v1.4.1                                               │     │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │     │
│  │  │ VirtualMachine │  │ VirtualMachine │  │ DataVolume     │  │     │
│  │  │ (migrated-vm-1)│  │ (migrated-vm-2)│  │ (disk storage) │  │     │
│  │  └────────────────┘  └────────────────┘  └────────────────┘  │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                                │
│  │master-0  │ │master-1  │ │master-2  │  NFS StorageClass: nfs-client  │
│  │10.9.21.151│ │10.9.21.152│ │10.9.21.153│                              │
│  └──────────┘ └──────────┘ └──────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Migration Lifecycle

```
  Source Hypervisor          ShiftWise Platform           OpenShift Cluster
  ================          ==================           =================

  ┌──────────────┐     1. DISCOVER                       
  │ VMware       │────────────────►┌──────────────┐      
  │ vSphere      │                 │  VM Inventory │      
  └──────────────┘                 │  (PostgreSQL) │      
  ┌──────────────┐                 └───────┬───────┘      
  │ libvirt/KVM  │────────────────►        │              
  └──────────────┘                         │              
  ┌──────────────┐     2. ANALYZE         │              
  │ Hyper-V      │────────────────►┌──────▼───────┐      
  └──────────────┘                 │ Compatibility │      
                                   │ Assessment    │      
                                   └───────┬───────┘      
                                           │              
                                   3. CONVERT              
                                   ┌───────▼───────┐      
                                   │ qemu-img      │      
                                   │ VMDK→QCOW2    │      
                                   │ Config fixes   │     
                                   └───────┬───────┘      
                                           │              
                                   4. MIGRATE             
                                   ┌───────▼───────┐     ┌──────────────┐
                                   │ Upload disk   │────►│ PVC (NFS)    │
                                   │ Create VM CR  │────►│ KubeVirt VM  │
                                   │ Health check  │     │ Running ✅   │
                                   └───────┬───────┘     └──────────────┘
                                           │              
                                   5. REPORT              
                                   ┌───────▼───────┐      
                                   │ Dashboard     │      
                                   │ Audit logs    │      
                                   │ Status stream │      
                                   └───────────────┘      
```

---

## Backend Architecture

### Layered Design

```
┌────────────────────────────────────────────────────────┐
│  HTTP Layer (api/v1/*.py)                              │
│  Route handlers, request parsing, response formatting  │
├────────────────────────────────────────────────────────┤
│  Dependency Layer (api/deps.py)                        │
│  Auth, DB sessions, RBAC enforcement                   │
├────────────────────────────────────────────────────────┤
│  Schema Layer (schemas/*.py)                           │
│  Pydantic models for validation & serialization        │
├────────────────────────────────────────────────────────┤
│  CRUD Layer (crud/*.py)                                │
│  Database operations with tenant scoping               │
├────────────────────────────────────────────────────────┤
│  Service Layer (services/*.py)                         │
│  Business logic: discovery, analysis, conversion       │
├────────────────────────────────────────────────────────┤
│  Model Layer (models/*.py)                             │
│  SQLAlchemy ORM definitions                            │
├────────────────────────────────────────────────────────┤
│  Core Layer (core/*.py)                                │
│  Config, DB engine, security, KubeVirt client          │
└────────────────────────────────────────────────────────┘
```

### Request Lifecycle

```
Client Request
    │
    ▼
┌─ FastAPI Router ─────────────────────┐
│  1. Parse request body (Schema)      │
│  2. Inject dependencies (deps.py)    │
│     a. Get DB session                │
│     b. Validate JWT → get user       │
│     c. Check RBAC permissions        │
│  3. Call CRUD/Service layer          │
│  4. Return response (Schema)         │
└──────────────────────────────────────┘
```

---

## Data Model

```
┌──────────────────────────────────────────────────────────────────┐
│                         BaseModel                                 │
│  id (UUID PK) | created_at (UTC) | updated_at (UTC)              │
└──────────────────────────────────────────────────────────────────┘
         △                △               △              △
         │                │               │              │
   ┌─────┴─────┐  ┌──────┴──────┐  ┌────┴─────┐  ┌───┴────────┐
   │    User    │  │  Hypervisor │  │   Role   │  │  Migration │
   ├───────────┤  ├─────────────┤  ├──────────┤  ├────────────┤
   │email      │  │name         │  │name      │  │vm_id (FK)  │
   │full_name  │  │type (enum)  │  │perms(JSON)│ │strategy    │
   │tenant_id  │  │host, port   │  │is_system │  │status      │
   │is_active  │  │credentials  │  └──────────┘  │timing      │
   │roles (M2M)│  │status       │                 └────────────┘
   └───────────┘  │tenant_id    │                       │
        │         └─────────────┘                       │
        │                │ 1:N                          │ N:1
        │         ┌──────▼──────────┐                   │
        │         │ VirtualMachine  │◄──────────────────┘
        │         ├─────────────────┤
        │         │name, specs      │
        │         │os_type (enum)   │
        │         │status (enum)    │
        │         │compatibility    │
        │         │tenant_id        │
        │         └─────────────────┘
        │
   ┌────▼────┐
   │user_roles│  (M2M Join Table)
   └──────────┘
```

---

## Security Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     Security Layers                             │
│                                                                 │
│  1. TRANSPORT      HTTPS/TLS encryption                        │
│  2. AUTHENTICATION JWT tokens (access + refresh)               │
│  3. AUTHORIZATION  RBAC permission matrix per role             │
│  4. DATA ISOLATION Multi-tenancy (tenant_id scoping)           │
│  5. PASSWORD       bcrypt hashing (72-byte limit)              │
│  6. CLUSTER AUTH   ServiceAccount / kubeconfig / custom token  │
└────────────────────────────────────────────────────────────────┘
```

---

## Infrastructure Architecture

```
                    Internet
                       │
                       ▼
              ┌────────────────┐
              │    HAProxy     │
              │  (10.9.21.150) │
              │  Ports: 6443,  │
              │  443, 80, 22623│
              └───────┬────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
   │master-0 │  │master-1 │  │master-2 │
   │  .151   │  │  .152   │  │  .153   │
   │ RHCOS   │  │ RHCOS   │  │ RHCOS   │
   │ KubeVirt│  │ KubeVirt│  │ KubeVirt│
   └────┬────┘  └────┬────┘  └────┬────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
              ┌───────▼───────┐
              │  NFS Server   │
              │  (10.9.21.154)│
              │  nfs-client   │
              │  StorageClass │
              └───────────────┘
```

---

## Migration Pipeline

### Strategy Selection

| Strategy | When Used | Steps |
|----------|-----------|-------|
| **Direct** | VM is fully compatible | Validate → Upload disk → Create KubeVirt VM |
| **Conversion** | VM is partially compatible | Validate → Convert disk → Fix config → Upload → Create VM |
| **Alternative** | VM is incompatible | Validate → Re-platform assessment → Custom approach |

### Pipeline Stages

```
[Pre-Check] → [Disk Process] → [Transfer] → [Deploy] → [Validate] → [Complete]

Pre-Check:    Verify source VM, check target cluster capacity
Disk Process: Convert VMDK/VHD → QCOW2 (if needed) via qemu-img
Transfer:     Upload converted disk to NFS PVC on OpenShift
Deploy:       Create KubeVirt VirtualMachine CR with proper spec
Validate:     Health check — VM boots, network reachable
Complete:     Update migration status, journal events, notify user
```
