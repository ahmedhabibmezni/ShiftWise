# 📡 ShiftWise API Reference

> Complete reference for all ShiftWise RESTful API endpoints.

**Base URL:** `http://localhost:8000/api/v1`  
**Auth:** JWT Bearer Token  
**Content-Type:** `application/json`  
**Documentation UI:** [Swagger UI](http://localhost:8000/docs) · [ReDoc](http://localhost:8000/redoc)

---

## 📋 Table of Contents

- [Authentication](#-authentication)
- [Users](#-users)
- [Roles](#-roles)
- [Virtual Machines](#-virtual-machines)
- [Hypervisors](#-hypervisors)
- [Migrations](#-migrations)
- [KubeVirt / OpenShift](#️-kubevirt--openshift)
- [Health & Status](#-health--status)
- [Error Handling](#-error-handling)

---

## 🔑 Authentication

### Login

```http
POST /api/v1/auth/login
Content-Type: application/json
```

**Request Body:**
```json
{
  "email": "admin@shiftwise.io",
  "password": "SecurePass123"
}
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Errors:** `401 Unauthorized` — Invalid credentials

---

### Refresh Token

```http
POST /api/v1/auth/refresh
Authorization: Bearer <refresh_token>
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

---

### Get Current User

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

**Response `200 OK`:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "admin@shiftwise.io",
  "full_name": "Admin User",
  "tenant_id": "nextstep",
  "is_active": true,
  "roles": [
    { "id": "...", "name": "admin", "permissions": { ... } }
  ],
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-14T08:00:00Z"
}
```

---

## 👤 Users

> **Min Role:** `admin` (tenant-scoped) · `super_admin` for delete

### List Users

```http
GET /api/v1/users?skip=0&limit=20
Authorization: Bearer <token>
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | Offset for pagination |
| `limit` | int | 20 | Page size (max 100) |

**Response `200 OK`:** Array of user objects

---

### Create User

```http
POST /api/v1/users
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "password": "StrongP@ss123",
  "full_name": "Jane Doe",
  "tenant_id": "nextstep",
  "role_ids": ["<role-uuid>"]
}
```

**Response `201 Created`:** Created user object

---

### Get User

```http
GET /api/v1/users/{user_id}
Authorization: Bearer <token>
```

**Response `200 OK`:** User object  
**Errors:** `404 Not Found`

---

### Update User

```http
PUT /api/v1/users/{user_id}
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "full_name": "Jane Updated",
  "is_active": false
}
```

**Response `200 OK`:** Updated user object

---

### Delete User

```http
DELETE /api/v1/users/{user_id}
Authorization: Bearer <token>
```

**Response `200 OK`:** Deleted user object  
**Errors:** `403 Forbidden` (requires `super_admin`)

---

## 🛡 Roles

> **Min Role:** `admin` for read · `super_admin` for write

### List Roles

```http
GET /api/v1/roles
Authorization: Bearer <token>
```

**Response `200 OK`:**
```json
[
  {
    "id": "...",
    "name": "admin",
    "description": "Full tenant management",
    "permissions": {
      "users": ["read", "create", "update"],
      "roles": ["read"],
      "vms": ["*"],
      "migrations": ["*"]
    },
    "is_system_role": true,
    "is_active": true
  }
]
```

---

### Create Custom Role

```http
POST /api/v1/roles
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "name": "migration_operator",
  "description": "Can manage migrations but not users",
  "permissions": {
    "vms": ["read"],
    "migrations": ["read", "create", "update"],
    "reports": ["read"]
  }
}
```

---

## 💻 Virtual Machines

> **Min Role:** `viewer` for read · `user` for write · `admin` for delete

### List VMs

```http
GET /api/v1/vms?skip=0&limit=50
Authorization: Bearer <token>
```

**Response `200 OK`:**
```json
[
  {
    "id": "...",
    "name": "web-server-01",
    "hypervisor_id": "...",
    "vcpus": 4,
    "memory_mb": 8192,
    "disk_size_gb": 100.0,
    "os_type": "linux",
    "status": "running",
    "compatibility_status": "compatible",
    "tenant_id": "nextstep",
    "created_at": "2026-03-10T14:00:00Z"
  }
]
```

### VM Enums

<details>
<summary><strong>VMStatus</strong></summary>

`running`, `stopped`, `suspended`, `migrating`, `error`, `unknown`

</details>

<details>
<summary><strong>CompatibilityStatus</strong></summary>

`compatible`, `partially_compatible`, `incompatible`, `not_analyzed`

</details>

<details>
<summary><strong>OSType</strong></summary>

`linux`, `windows`, `other`

</details>

---

## 🖥 Hypervisors

> **Min Role:** `admin`

### Register Hypervisor

```http
POST /api/v1/hypervisors
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "name": "vCenter-Production",
  "type": "vmware",
  "host": "vcenter.example.com",
  "port": 443,
  "username": "admin@vsphere.local",
  "password": "SecurePass",
  "tenant_id": "nextstep"
}
```

### Hypervisor Enums

<details>
<summary><strong>HypervisorType</strong></summary>

`vmware`, `libvirt`, `hyperv`

</details>

<details>
<summary><strong>HypervisorStatus</strong></summary>

`connected`, `disconnected`, `error`

</details>

---

## 🔄 Migrations

> **Min Role:** `viewer` for read · `user` for create · `admin` for delete/cancel

### Create Migration

```http
POST /api/v1/migrations
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "vm_id": "550e8400-e29b-41d4-a716-446655440000",
  "strategy": "conversion"
}
```

**Response `201 Created`:**
```json
{
  "id": "...",
  "vm_id": "...",
  "strategy": "conversion",
  "status": "pending",
  "started_at": null,
  "completed_at": null,
  "error_message": null,
  "tenant_id": "nextstep",
  "created_at": "2026-03-14T08:00:00Z"
}
```

### Migration Enums

<details>
<summary><strong>MigrationStrategy</strong></summary>

`direct`, `conversion`, `alternative`

</details>

<details>
<summary><strong>MigrationStatus</strong></summary>

`pending`, `in_progress`, `completed`, `failed`, `cancelled`

</details>

---

## ☸️ KubeVirt / OpenShift

> **Min Role:** `admin`

### List Namespaces

```http
GET /api/v1/kubevirt/namespaces
Authorization: Bearer <token>
```

### List KubeVirt VMs

```http
GET /api/v1/kubevirt/vms?namespace=default
Authorization: Bearer <token>
```

### Create KubeVirt VM

```http
POST /api/v1/kubevirt/vms
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "name": "migrated-web-server",
  "namespace": "migration-ns",
  "cpu_cores": 4,
  "memory": "8Gi",
  "disk_image": "pvc-name"
}
```

### Delete KubeVirt VM

```http
DELETE /api/v1/kubevirt/vms/{vm_name}?namespace=default
Authorization: Bearer <token>
```

---

## 💚 Health & Status

### Root

```http
GET /
```

```json
{
  "name": "ShiftWise",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "description": "Migration Intelligente de VMs vers OpenShift"
}
```

### Health Check

```http
GET /health
```

```json
{
  "status": "healthy",
  "app": "ShiftWise",
  "version": "1.0.0"
}
```

---

## ❌ Error Handling

All errors follow a consistent JSON format:

```json
{
  "detail": "Error description"
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `400` | Bad Request — validation error |
| `401` | Unauthorized — invalid/missing token |
| `403` | Forbidden — insufficient permissions |
| `404` | Not Found — resource does not exist |
| `422` | Unprocessable Entity — schema validation failure |
| `500` | Internal Server Error — unexpected exception |

In debug mode (`DEBUG=True`), 500 errors include:

```json
{
  "detail": "Error message",
  "type": "ExceptionClassName",
  "path": "/api/v1/endpoint"
}
```