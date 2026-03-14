# 🏗 Infrastructure

Configuration files and validation scripts for the ShiftWise OpenShift deployment environment. This directory contains the complete infrastructure-as-config for the bastion node services and OpenShift cluster setup.

---

## 📁 Directory Structure

```
infrastructure/
├── chrony/                     # NTP time synchronization
│   ├── chrony.conf             # Chrony configuration
│   └── validate-chrony.sh      # Validation script
├── dns/                        # DNS (BIND/named)
│   ├── named.conf              # BIND configuration
│   ├── migration.nextstep-it.com.zone  # Forward DNS zone
│   ├── 21.9.10.in-addr.arpa.zone      # Reverse DNS zone
│   └── validate-dns.sh         # Validation script
├── haproxy/                    # Load Balancer
│   ├── haproxy.cfg             # HAProxy configuration
│   └── validate-haproxy.sh     # Validation script
├── httpd/                      # Apache HTTP Server
│   ├── openshift4.conf         # HTTP server configuration
│   └── validate-httpd.sh       # Validation script
└── openshift/                  # OpenShift Cluster
    ├── install-config.yaml     # OpenShift install configuration
    └── README.md               # OpenShift-specific docs
```

---

## 🖥 Cluster Topology

```
┌────────────────────────────────────────────────────────────────────┐
│                      Network: 10.9.21.0/24                         │
│                                                                    │
│  ┌─────────────────────┐                                          │
│  │  BASTION NODE        │    Domain: migration.nextstep-it.com    │
│  │  10.9.21.150         │                                          │
│  │  RHEL 9.6            │                                          │
│  │                      │    ┌─────────────────────────────────┐  │
│  │  ┌──────────────┐   │    │   OPENSHIFT 4.18.1 CLUSTER      │  │
│  │  │ DNS (BIND)   │   │    │   Compact: 3 master+worker      │  │
│  │  │ HAProxy      │   │    │   Bare Metal UPI                 │  │
│  │  │ HTTP (Apache)│   │    │                                   │  │
│  │  │ NTP (Chrony) │   │    │   master-0  10.9.21.151 RHCOS   │  │
│  │  └──────────────┘   │    │   master-1  10.9.21.152 RHCOS   │  │
│  └─────────────────────┘    │   master-2  10.9.21.153 RHCOS   │  │
│                              │                                   │  │
│  ┌─────────────────────┐    │   KubeVirt v1.4.1                │  │
│  │  NFS SERVER          │    │   virtctl: /usr/local/bin/virtctl│  │
│  │  10.9.21.154         │    └─────────────────────────────────┘  │
│  │  Ubuntu 24.04        │                                          │
│  │  StorageClass:       │    Access Points:                       │
│  │  nfs-client (default)│    Console: console-openshift-console   │
│  └─────────────────────┘            .apps.migration.nextstep-it.com│
│                              API: api.migration.nextstep-it.com:6443│
└────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Component Details

### 🕐 Chrony (NTP)

**File:** `chrony/chrony.conf`

Provides time synchronization across all cluster nodes. Accurate time is critical for:
- Certificate validation
- Log correlation across nodes
- etcd consistency in the OpenShift cluster

| Setting | Value |
|---------|-------|
| Upstream NTP | Configured to bastion or public NTP servers |
| Serve to subnet | `10.9.21.0/24` |

### 🌐 DNS (BIND)

**Files:** `dns/named.conf`, `dns/migration.nextstep-it.com.zone`, `dns/21.9.10.in-addr.arpa.zone`

DNS is the foundational service for OpenShift. It resolves all cluster hostnames.

| Record | Resolves To |
|--------|-------------|
| `api.migration.nextstep-it.com` | `10.9.21.150` (bastion/HAProxy) |
| `api-int.migration.nextstep-it.com` | `10.9.21.150` |
| `*.apps.migration.nextstep-it.com` | `10.9.21.150` |
| `master-0.migration.nextstep-it.com` | `10.9.21.151` |
| `master-1.migration.nextstep-it.com` | `10.9.21.152` |
| `master-2.migration.nextstep-it.com` | `10.9.21.153` |
| `bastion.migration.nextstep-it.com` | `10.9.21.150` |
| `nfs.migration.nextstep-it.com` | `10.9.21.154` |

### ⚖️ HAProxy (Load Balancer)

**File:** `haproxy/haproxy.cfg`

Routes traffic to the OpenShift cluster nodes:

| Frontend | Port | Backend |
|----------|------|---------|
| Kubernetes API | 6443 | `master-0:6443`, `master-1:6443`, `master-2:6443` |
| Machine Config Server | 22623 | `master-0:22623`, `master-1:22623`, `master-2:22623` |
| HTTPS Ingress | 443 | `master-0:443`, `master-1:443`, `master-2:443` |
| HTTP Ingress | 80 | `master-0:80`, `master-1:80`, `master-2:80` |

### 🌍 Apache HTTP (httpd)

**File:** `httpd/openshift4.conf`

Serves ignition files and RHCOS images required during the OpenShift bare metal installation process.

| Purpose | Path |
|---------|------|
| Ignition configs | Bootstrap, master, worker ignition files |
| RHCOS images | Bare metal ISO/raw images for PXE boot |

---

## ✅ Validation Scripts

Each component includes a validation script to verify correct configuration:

```bash
# Validate all services
bash infrastructure/chrony/validate-chrony.sh
bash infrastructure/dns/validate-dns.sh
bash infrastructure/haproxy/validate-haproxy.sh
bash infrastructure/httpd/validate-httpd.sh
```

| Script | Checks |
|--------|--------|
| `validate-chrony.sh` | Time sync status, upstream reachability |
| `validate-dns.sh` | Forward/reverse resolution for all cluster records |
| `validate-haproxy.sh` | Backend health, port bindings |
| `validate-httpd.sh` | HTTP serving, ignition file availability |