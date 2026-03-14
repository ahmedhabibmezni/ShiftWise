# ☸️ OpenShift Cluster Configuration

Configuration files for the ShiftWise OpenShift 4.18.1 compact cluster deployed via bare metal User Provisioned Infrastructure (UPI).

---

## 📋 Cluster Specifications

| Parameter | Value |
|-----------|-------|
| **OpenShift Version** | 4.18.1 |
| **Deployment Method** | Bare Metal UPI |
| **Cluster Topology** | Compact (3 master+worker nodes) |
| **Node OS** | Red Hat CoreOS (RHCOS) 4.18 |
| **Domain** | `migration.nextstep-it.com` |
| **API VIP** | `api.migration.nextstep-it.com` → `10.9.21.150` |
| **Ingress VIP** | `*.apps.migration.nextstep-it.com` → `10.9.21.150` |
| **KubeVirt Version** | v1.4.1 |
| **Default StorageClass** | `nfs-client` (NFS provisioner) |

---

## 🖥 Node Inventory

| Node | Hostname | IP Address | Roles |
|------|----------|------------|-------|
| master-0 | `master-0.migration.nextstep-it.com` | `10.9.21.151` | master, worker |
| master-1 | `master-1.migration.nextstep-it.com` | `10.9.21.152` | master, worker |
| master-2 | `master-2.migration.nextstep-it.com` | `10.9.21.153` | master, worker |

---

## 📄 `install-config.yaml`

The OpenShift installer configuration used to generate ignition configs during cluster installation.

Key parameters:
- **Base domain:** `nextstep-it.com`
- **Cluster name:** `migration`
- **Control plane replicas:** 3
- **Compute replicas:** 0 (compact cluster — masters serve as workers)
- **Network type:** OVNKubernetes
- **Platform:** `none` (bare metal)

---

## 🔧 KubeVirt Integration

KubeVirt v1.4.1 is installed on the cluster, enabling VM workloads alongside containers.

### Installed Components

| Component | Description |
|-----------|-------------|
| `virt-operator` | Manages KubeVirt lifecycle |
| `virt-controller` | Handles VirtualMachine state transitions |
| `virt-handler` | DaemonSet on each node for VM management |
| `virt-api` | API server for KubeVirt resources |
| `virtctl` | CLI tool at `/usr/local/bin/virtctl` |

### Key CRDs

| CRD | Purpose |
|-----|---------|
| `VirtualMachine` | Declarative VM definition (persistent) |
| `VirtualMachineInstance` | Running VM instance (ephemeral) |
| `DataVolume` | Storage provisioning for VM disks |

### Storage

| StorageClass | Provisioner | Access Mode | Default |
|-------------|-------------|-------------|---------|
| `nfs-client` | NFS external provisioner | ReadWriteMany | ✅ Yes |

VM disks are stored as Persistent Volume Claims (PVCs) backed by the NFS `nfs-client` StorageClass.

---

## 🌐 Access Points

| Service | URL |
|---------|-----|
| Web Console | `https://console-openshift-console.apps.migration.nextstep-it.com` |
| API Server | `https://api.migration.nextstep-it.com:6443` |
| OAuth | `https://oauth-openshift.apps.migration.nextstep-it.com` |
| Monitoring | `https://grafana-openshift-monitoring.apps.migration.nextstep-it.com` |

---

## 🚀 Connecting to the Cluster

### Using `oc` CLI

```bash
# Login via token
oc login https://api.migration.nextstep-it.com:6443 --token=<token>

# Login via credentials
oc login https://api.migration.nextstep-it.com:6443 -u kubeadmin -p <password>

# Verify connection
oc get nodes
oc get kubevirt -n kubevirt
```

### Using `virtctl`

```bash
# List VMs
virtctl get vms -n default

# Start a VM
virtctl start <vm-name> -n <namespace>

# Console access
virtctl console <vm-name> -n <namespace>

# SSH into VM
virtctl ssh <user>@<vm-name> -n <namespace>
```

### From ShiftWise Backend

The backend connects to this cluster via the KubeVirt client using one of three modes configured in `.env`:

```env
KUBERNETES_MODE=kubeconfig
KUBECONFIG_PATH=./config/kubeconfig
```