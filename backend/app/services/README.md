# 🧠 Services Layer (`services/`)

Business-logic services implementing the ShiftWise migration pipeline — VM discovery, compatibility analysis, disk conversion, guest-OS adaptation, and migration execution.

---

## 🔄 Migration Pipeline

```
Discovery → Analyzer → Converter → Adapter → Migrator → Reporting
```

The Converter, Adapter, and Migrator stages are orchestrated asynchronously by Celery tasks (`app/tasks/`), backed by Redis, and submit Kubernetes Jobs to the OpenShift cluster.

---

## 📁 Layout

| Path | Description |
|------|-------------|
| `discovery.py` | VM discovery connectors for all supported hypervisors |
| `analyzer.py` | Compatibility analysis service (hybrid rules + ML) |
| `compatibility_rules.py` | Rule-based feature extraction |
| `feature_extractor.py` | Feature-vector construction for the ML model |
| `converter/` | Disk format conversion (package) |
| `adapter/` | Guest-OS fixup (package) |
| `migrator/` | PVC populate + KubeVirt VM creation (package) |

---

## 🔍 `discovery.py` — VM Discovery

Connects to registered hypervisors and inventories their virtual machines.

| Hypervisor | Mechanism |
|------------|-----------|
| VMware Workstation | `vmrun` + VMX file scan |
| Microsoft Hyper-V | PowerShell over SSH (`paramiko`) |
| libvirt / KVM | `paramiko` SSH + `virsh` |
| Proxmox VE | REST API (`proxmoxer`) |
| oVirt / RHV | `ovirt-engine-sdk-python` |
| VMware vSphere | Stub — no test environment available (free ESXi discontinued) |

Rediscovery is scoped to the source hypervisor to avoid cross-hypervisor name collisions. On re-sync, the `MIGRATING` and `MIGRATED` statuses are preserved while other VMs are reset to `DISCOVERED`.

---

## 🧪 `analyzer.py` — Compatibility Analyzer

Hybrid rule-based + machine-learning compatibility assessment:

1. `compatibility_rules.py` extracts rule-based features from a VM's configuration.
2. `feature_extractor.py` builds the numeric feature vector.
3. A scikit-learn classifier (trained artifacts in `app/ml/`) produces a **0–100% score** via `predict_proba()`.
4. The VM is classified `COMPATIBLE`, `PARTIAL`, or `INCOMPATIBLE`.

The trained model is loaded from a `joblib` artifact at service startup. If the artifact is missing, the analyzer degrades gracefully to a rules-only assessment.

---

## 💿 `converter/` — Disk Converter

Converts source disks (VMDK / VHD → QCOW2) by submitting `qemu-img` Kubernetes Jobs that operate on the NFS transit zone.

| Module | Responsibility |
|--------|----------------|
| `connectors/` | Per-hypervisor source-disk export (`vmware_workstation`, `hyperv`, `kvm`, `proxmox`, `ovirt`, `vsphere`; `base` protocol) |
| `plan.py` | Builds the per-VM conversion plan |
| `k8s_jobs.py` | Kubernetes Job manifests for `qemu-img` |
| `paths.py` | NFS transit-zone path resolution |
| `protocol.py` | Connector interface protocol |
| `remote_transit.py` | Dev/demo only — bastion-jump SFTP upload of a converted qcow2 to the transit NFS (`CONVERTER_SOURCE_CONVERT_SFTP`) |
| `service.py` | Conversion orchestration (in-cluster `qemu-img` Job, or the gated convert-on-source SFTP path) |
| `errors.py` | Conversion error catalog |

> **Convert-on-source mode** (`CONVERTER_SOURCE_CONVERT_SFTP=True`, default off): for local development where the worker reaches the source hypervisor but not the cluster NFS, the Proxmox connector runs `qemu-img convert -c` on the source node and the worker uploads the small qcow2 to the transit NFS over SSH. Production keeps the in-cluster `qemu-img` Job path.

---

## 🛠 `adapter/` — Guest-OS Adapter

Sits between the Converter and the Migrator. Submits a Kubernetes Job per disk that runs `virt-customize` (libguestfs) on the converted QCOW2 in place:

- 4 parallel DHCP configurations (systemd-networkd, ifupdown, NetworkManager keyfile, netplan)
- serial-console enablement (`serial-getty@ttyS0` + GRUB serial redirect) — note: the `systemctl` enable is a no-op on non-systemd guests (Alpine/OpenRC), which then have no `ttyS0` login; use the graphical console
- SELinux relabel

Required because KubeVirt exposes a virtio NIC (`enp1s0`/`ens2`) while the source guest is configured for the VMware NIC (`ens33`/`eth0`).

Runs in a **privileged** pod (`ADAPTER_PRIVILEGED=True`) and forces the libguestfs **TCG** backend (the nodes expose no usable in-pod KVM acceleration). The Job runs as the per-tenant `shiftwise-populator` SA, which carries the `nfs`-volume SCC.

| Module | Responsibility |
|--------|----------------|
| `guestfish_job.py` | Job manifest + the in-place `virt-customize` fixup script |
| `service.py` | Adapter orchestration |
| `errors.py` | Adapter error catalog |

---

## 🚚 `migrator/` — Migration Engine

The final stage — populates the target PVC and creates the KubeVirt VirtualMachine.

| Module | Responsibility |
|--------|----------------|
| `transit_discovery.py` | Auto-discovers the NFS transit server/path from the bound transit PV |
| `namespace.py` | Idempotent tenant-namespace creation (+ opt-in `ResourceQuota`) + per-tenant `shiftwise-populator` SA & SCC grant (`ensure_populator_scc`) |
| `pvc.py` | Target PVC sizing and creation |
| `populator_job.py` | NFS-direct `qemu-img` populate Job |
| `vm_manifest.py` | KubeVirt `VirtualMachine` manifest builder |
| `service.py` | Migration orchestration (PVC populate → VM create → verify) |
| `errors.py` | Migrator error catalog |
