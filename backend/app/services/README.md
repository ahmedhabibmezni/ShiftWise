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
| `discovery.py` | VM discovery connectors for all supported hypervisors + physical (P2V) hosts |
| `analyzer.py` | Compatibility analysis service (hybrid rules + ML) |
| `compatibility_rules.py` | Rule-based feature extraction |
| `feature_extractor.py` | Feature-vector construction for the ML model |
| `strategy.py` | Maps the compatibility score to a `MigrationStrategy` (auto-selection) |
| `converter/` | Disk format conversion (package) |
| `adapter/` | Guest-OS fixup (package) |
| `migrator/` | PVC populate + KubeVirt VM creation (package) |
| `cluster/` | Effective cluster-config resolver + `(scope_key, config_version)` client cache + connection probe (feature 002) |

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
| VMware vSphere / ESXi | `pyVmomi` `SmartConnect` (works against standalone ESXi); covered by mocked tests — no permanent live endpoint in CI |
| Physical Linux (P2V) | `paramiko` SSH — read-only fact commands + `lsblk -b -J` disk plan; the host is the migration source (no hypervisor, no disk image file) |

For a **physical (P2V)** source, discovery emits a single VM dict for the host (UUID from the DMI `product_uuid`, else synthetic `physical-{hostname}`) and persists the per-block-device capture plan in `vm.custom_metadata["physical_disks"]` for the converter.

Rediscovery is scoped to the source hypervisor to avoid cross-hypervisor name collisions. On re-sync, the `MIGRATING` and `MIGRATED` statuses are preserved while other VMs are reset to `DISCOVERED`.

---

## 🧪 `analyzer.py` — Compatibility Analyzer

Hybrid rule-based + machine-learning compatibility assessment:

1. `compatibility_rules.py` extracts rule-based features from a VM's configuration.
2. `feature_extractor.py` builds the numeric feature vector.
3. A scikit-learn classifier (trained artifacts in `app/ml/`) plus the rules engine produce a **0–100 score**. The rules score is **intervention-based** — `100 − Σ penalties`, where each failing rule's `weight` reflects the pipeline work it implies (e.g. disk conversion, virtio driver injection). A hard blocker zeroes eligibility.
4. The VM is classified `COMPATIBLE`, `PARTIAL`, or `INCOMPATIBLE`.
5. `strategy.py:recommend_strategy` maps the score to a `MigrationStrategy` band (≥90 `DIRECT`, ≥70 `CONVERSION`, ≥50 `HYBRID`, else `COLD`; `None` on a blocker). The result is persisted as `recommended_strategy` and auto-selected when a migration is created (fallback `AUTO`).

The trained model is loaded from a `joblib` artifact at service startup. If the artifact is missing or version-skewed, the analyzer degrades gracefully to a rules-only assessment.

---

## 💿 `converter/` — Disk Converter

Converts source disks (VMDK / VHD / raw → QCOW2) by submitting `qemu-img` Kubernetes Jobs that operate on the NFS transit zone.

| Module | Responsibility |
|--------|----------------|
| `connectors/` | Per-source disk export (`vmware_workstation`, `hyperv`, `kvm`, `proxmox`, `ovirt`, `vsphere`, `physical`; `base` protocol) |
| `plan.py` | Builds the per-VM conversion plan |
| `k8s_jobs.py` | Kubernetes Job manifests for `qemu-img` |
| `paths.py` | NFS transit-zone path resolution |
| `protocol.py` | Connector interface protocol |
| `remote_transit.py` | Dev/demo only — bastion-jump SFTP upload of a converted qcow2 to the transit NFS (`CONVERTER_SOURCE_CONVERT_SFTP`) |
| `service.py` | Conversion orchestration (in-cluster `qemu-img` Job, or the gated convert-on-source SFTP path) |
| `errors.py` | Conversion error catalog |

> **Convert-on-source mode** (`CONVERTER_SOURCE_CONVERT_SFTP=True`, default off): for local development where the worker reaches the source hypervisor but not the cluster NFS, the Proxmox connector runs `qemu-img convert -c` on the source node and the worker uploads the small qcow2 to the transit NFS over SSH. Production keeps the in-cluster `qemu-img` Job path.

> **Physical (P2V) connector** (`connectors/physical.py`): the bare-metal host has no disk image and no `qemu-img`. It streams each block device as `dd if=<dev> bs=4M conv=noerror,sync | gzip -1` over SSH into a staged `.raw` on NFS (sha256-verified); the raw→qcow2 step runs on the worker. The K8s `qemu-img` Job passes `-f raw` for raw source disks.

---

## 🛠 `adapter/` — Guest-OS Adapter

Sits between the Converter and the Migrator. Submits a Kubernetes Job per disk that runs `virt-customize` (libguestfs) on the converted QCOW2 in place:

- 4 parallel DHCP configurations (systemd-networkd, ifupdown, NetworkManager keyfile, netplan)
- serial-console enablement (`serial-getty@ttyS0` + GRUB serial redirect) — note: the `systemctl` enable is a no-op on non-systemd guests (Alpine/OpenRC), which then have no `ttyS0` login; use the graphical console
- SELinux relabel
- **physical (P2V) source only** (`is_physical`): regenerates the guest initramfs with `virtio_blk/net/pci/scsi` forced in (`update-initramfs` + `dracut`) — a bare-metal initramfs has no virtio modules, so the guest would panic on KubeVirt's virtio bus

The OS/source branch lives in `_fixup_script_for_os(os_type, is_physical=...)`, which also carries the `os_type=WINDOWS` → `virt-v2v-in-place` (virtio-win) path.

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
