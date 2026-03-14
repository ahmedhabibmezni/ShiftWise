# 🧠 Services Layer (`services/`)

Business logic services that implement the core ShiftWise intelligence — VM discovery, compatibility analysis, disk conversion, and migration orchestration.

---

## 📁 Files

| File | Status | Description |
|------|--------|-------------|
| `discovery.py` | 🚧 In Development | Auto-discover VMs from connected hypervisors |

---

## ✅ `discovery.py` — VM Discovery Service

The discovery service connects to registered hypervisors and automatically inventories virtual machines.

### Supported Hypervisors

| Hypervisor | SDK | Discovery Method |
|------------|-----|-----------------|
| VMware vSphere | `pyvmomi` | vCenter/ESXi API queries |
| libvirt / KVM | `libvirt-python` | libvirt domain enumeration |
| Hyper-V | `paramiko` + WMI | PowerShell remoting over SSH |

### Discovery Workflow

```
┌────────────────┐     ┌───────────────────┐     ┌──────────────────┐
│  Get Hypervisor│────▶│  Connect to API   │────▶│  Enumerate VMs   │
│  Credentials   │     │  (vSphere/libvirt/│     │  (name, CPU, RAM │
│  from DB       │     │   Hyper-V)        │     │   disk, OS)      │
└────────────────┘     └───────────────────┘     └────────┬─────────┘
                                                          │
                                                 ┌────────▼─────────┐
                                                 │  Upsert VMs      │
                                                 │  into ShiftWise  │
                                                 │  Database        │
                                                 └──────────────────┘
```

---

## 🚧 Planned Services

### `analyzer.py` — Compatibility Analyzer

**Status:** Not yet implemented

**Planned scope:**
- Evaluate each discovered VM against OpenShift Virtualization requirements
- Classification output: `compatible`, `partially_compatible`, `incompatible`
- Analysis criteria:
  - OS type and version support
  - Disk format compatibility (VMDK, VHD, QCOW2)
  - Device drivers and virtio compatibility
  - Network adapter configuration
  - Boot firmware (BIOS vs UEFI)
- ML model (scikit-learn) trained on historical migration outcomes
- Guest filesystem inspection via `libguestfs` for deep OS analysis

---

### `converter.py` — Disk & Config Converter

**Status:** Not yet implemented

**Planned scope:**
- Automated disk format conversion using `qemu-img`:
  - VMDK → QCOW2
  - VHD/VHDX → QCOW2
- Configuration remediation for partially compatible VMs:
  - Inject virtio drivers
  - Adjust disk bus types
  - Fix network device models
- Conversion progress tracking with percentage updates
- Celery task integration for background processing

---

### `migrator.py` — Migration Engine

**Status:** Not yet implemented

**Planned scope:**
- Three migration strategies:
  - **Direct Migration** — for fully compatible VMs (minimal transformation)
  - **Conversion Migration** — for partially compatible VMs (convert then migrate)
  - **Alternative Migration** — for incompatible VMs (re-platform approach)
- AI-based strategy recommendation using VM characteristics
- Celery-orchestrated, multi-phase execution:
  1. Pre-migration validation
  2. Disk upload to NFS StorageClass
  3. KubeVirt VirtualMachine resource creation
  4. Post-migration health checks
- Rollback support on failure
- Real-time status updates via WebSocket

---

### `reporter.py` — Reporting Service

**Status:** Not yet implemented

**Planned scope:**
- Migration status aggregation (success rate, duration stats)
- Per-VM migration journal with timestamped events
- Dashboard data endpoint (counts, trends, active migrations)
- Export reports (JSON, CSV)
