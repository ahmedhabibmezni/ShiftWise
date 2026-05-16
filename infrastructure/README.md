# 🏗 Infrastructure

Configuration files and validation scripts for the ShiftWise OpenShift deployment environment. This directory contains the infrastructure-as-config for the bastion node services and the OpenShift cluster setup.

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
│   ├── 21.9.10.in-addr.arpa.zone       # Reverse DNS zone
│   └── validate-dns.sh         # Validation script
├── haproxy/                    # Load Balancer
│   ├── haproxy.cfg             # HAProxy configuration
│   └── validate-haproxy.sh     # Validation script
├── httpd/                      # Apache HTTP Server
│   ├── openshift4.conf         # HTTP server configuration
│   └── validate-httpd.sh       # Validation script
└── openshift/                  # OpenShift Cluster
    ├── install-config.yaml     # OpenShift install configuration
    ├── cluster-health.sh       # Cluster health-check script
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
│  │  ┌──────────────┐   │    │   OPENSHIFT 4.18.1 CLUSTER       │  │
│  │  │ DNS (BIND)   │   │    │   Compact: 3 control-plane+worker│  │
│  │  │ HAProxy      │   │    │   Bare Metal UPI                 │  │
│  │  │ HTTP (Apache)│   │    │                                   │  │
│  │  │ NTP (Chrony) │   │    │   node01   10.9.21.151  RHCOS    │  │
│  │  └──────────────┘   │    │   node02   10.9.21.152  RHCOS    │  │
│  └─────────────────────┘    │   node03   10.9.21.153  RHCOS    │  │
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
| `bastion.migration.nextstep-it.com` | `10.9.21.150` |
| `api.migration.nextstep-it.com` | `10.9.21.150` (bastion / HAProxy) |
| `api-int.migration.nextstep-it.com` | `10.9.21.150` |
| `*.apps.migration.nextstep-it.com` | `10.9.21.150` |
| `node01.migration.nextstep-it.com` | `10.9.21.151` |
| `node02.migration.nextstep-it.com` | `10.9.21.152` |
| `node03.migration.nextstep-it.com` | `10.9.21.153` |
| `etcd-0 / etcd-1 / etcd-2` | `10.9.21.151` / `.152` / `.153` |

A temporary `bootstrap` record (`10.9.21.156`) exists during cluster installation. The NFS server (`10.9.21.154`) is reached by IP and is not part of this zone.

### ⚖️ HAProxy (Load Balancer)

**File:** `haproxy/haproxy.cfg`

Routes traffic to the OpenShift cluster nodes (all three nodes are control-plane **and** worker):

| Frontend | Port | Backend |
|----------|------|---------|
| Kubernetes API | 6443 | `node01/02/03:6443` (+ `bootstrap` during install) |
| Machine Config Server | 22623 | `node01/02/03:22623` (+ `bootstrap` during install) |
| HTTPS Ingress | 443 | `node01/02/03:443` |
| HTTP Ingress | 80 | `node01/02/03:80` |

A statistics interface is exposed on port `9000`.

### 🌍 Apache HTTP (httpd)

**File:** `httpd/openshift4.conf`

Serves ignition files and RHCOS images required during the OpenShift bare-metal installation process.

| Purpose | Path |
|---------|------|
| Ignition configs | Bootstrap, master, worker ignition files |
| RHCOS images | Bare-metal ISO/raw images |

---

## ✅ Validation Scripts

Each bastion service includes a validation script to verify correct configuration:

```bash
bash infrastructure/chrony/validate-chrony.sh
bash infrastructure/dns/validate-dns.sh
bash infrastructure/haproxy/validate-haproxy.sh
bash infrastructure/httpd/validate-httpd.sh
```

| Script | Checks |
|--------|--------|
| `validate-chrony.sh` | Time-sync status, upstream reachability |
| `validate-dns.sh` | Forward/reverse resolution for all cluster records |
| `validate-haproxy.sh` | Backend health, port bindings |
| `validate-httpd.sh` | HTTP serving, ignition file availability |

For overall cluster health, `openshift/cluster-health.sh` checks node, operator, and KubeVirt status.
