# 📋 Changelog

All notable changes to the ShiftWise project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Work completed on the development branch since v1.0.0 — not yet part of a tagged release.

### ✨ Added

- **Live production deployment** — ShiftWise is deployed and reachable on the OpenShift cluster at `https://shiftwise.apps.migration.nextstep-it.com` (shared host: `/` → frontend, `/api` → backend). Admin login verified end-to-end; `GET /health` `healthy`. Access requires the on-prem VPN plus a hosts entry (or VPN DNS) resolving `*.apps.migration.nextstep-it.com` → the bastion router `10.9.21.150`.
- **GitOps CI/CD pipeline (activated)** — a `git push` now builds, scans, and ships the whole stack to the cluster with no cluster credentials in CI. `cd.yml` (gated on a green `ci.yml`) builds the single backend image **and** the fat worker image, Trivy-scans them (fails the deploy on a fixable HIGH/CRITICAL CVE), emits a CycloneDX SBOM per image, pushes immutable `sha-<commit>` tags to Docker Hub, then bumps the matching kustomize overlay (`develop` → staging, `main` → production) and commits. Argo CD (in-cluster, automated sync enabled on both Applications) reconciles the change. `release.yml` mints immutable `vX.Y.Z` images on a tag. See `backend/openshift/CICD-RUNBOOK.md`.
- **Migration tooling worker image** — `cd.yml` builds `shiftwise-backend-worker:sha-<commit>` from `backend/Dockerfile.worker` (`FROM` the API image + `qemu-utils`, `libguestfs-tools`, `linux-image-amd64`). The converter / adapter / populator Kubernetes Jobs point at it (`CONVERTER_CONTAINER_IMAGE` / `ADAPTER_IMAGE` / `MIGRATOR_POPULATOR_IMAGE`) with `imagePullPolicy: Always` so each deploy picks up the rolling tag.
- **Discovery Service** — real VM discovery connectors: VMware Workstation (`vmrun` + VMX scan), vSphere/ESXi (`pyVmomi` `SmartConnect`), Hyper-V (PowerShell over SSH), libvirt/KVM (paramiko SSH + `virsh`), Proxmox VE (REST API), oVirt/RHV (engine SDK), and physical Linux (P2V) over SSH.
- **Physical server (P2V) source** — migrate a bare-metal Linux host (no hypervisor, no disk image) to OpenShift Virtualization. New `HypervisorType.PHYSICAL` (migration `d1f8274d5e22`); SSH discovery collecting host facts + an `lsblk` block-device plan; a `PhysicalPuller` converter connector that captures each device as a `dd | gzip` raw stream over SSH; an adapter branch that regenerates the guest initramfs with virtio drivers (a bare-metal initramfs has none and would panic on KubeVirt's virtio bus). **Validated end-to-end**: a Debian Linux source — accessed purely over SSH with native tools, no hypervisor API — was captured, converted, adapted, and booted as a KubeVirt VM on the virtio bus. (A run against true bare-metal hardware driven by the in-cluster worker is still pending; the code path itself is proven.)
- **Real vSphere/ESXi connector** — replaced the previous fake-data vSphere stub with a `pyVmomi` `SmartConnect` implementation working against standalone ESXi (discovery + test-connection + disk conversion; `VMWARE_ESXi` routed through the same connector).
- **Analyzer Module** — hybrid compatibility scoring: rule-based feature extraction feeding a scikit-learn classifier; **intervention-based 0–100 score** (`100 − Σ penalties`, each failing rule weighted by the pipeline work it implies); analyze endpoints under `/api/v1/vms`.
- **Auto migration-strategy selection** — `services/strategy.py:recommend_strategy` maps the compatibility score to a `MigrationStrategy` band (≥90 `DIRECT`, ≥70 `CONVERSION`, ≥50 `HYBRID`, else `COLD`); persisted as `recommended_strategy` and applied automatically when a migration is created (fallback `AUTO`).
- **Converter Module** — disk format conversion (VMDK/VHD/raw → QCOW2) via `qemu-img` Kubernetes Jobs on an NFS transit zone; `/api/v1/conversions` router for job tracking.
- **Adapter Module** — guest-OS fixup via libguestfs/`virt-customize`: multi-stack DHCP configuration, serial-console enablement, SELinux relabel, and P2V virtio-initramfs regeneration. Runs as a Kubernetes Job between the Converter and Migrator stages.
- **Migrator Module** — PVC populate (NFS-direct `qemu-img` Job) and KubeVirt VirtualMachine creation, start, and verification; tenant namespace auto-creation; opt-in per-tenant ResourceQuota.
- **Celery + Redis orchestration** — asynchronous, durable migration pipeline wired to `POST /api/v1/migrations/{id}/start`.
- **OpenShift deployment** — `backend/openshift/` manifests (PostgreSQL, Redis, transit PVC, backend, Celery workers, Flower, RBAC, SCC) and a one-command idempotent `deploy.sh`.
- **Frontend SPA** *(in progress)* — React 19 + Vite + TypeScript + Tailwind; login, dashboard, hypervisors, VMs, migrations, reports, users, roles, settings, and infrastructure pages.
- **Cluster Connectivity Management (feature 002)** — DB-backed per-tenant cluster connection configuration replacing the static `scp kubeconfig` + restart workflow. New Administration **Infrastructure** page (`/api/v1/infrastructure`) lets a superadmin (or a tenant admin scoped to their own tenant) choose the connection mode (`kubeconfig` / `incluster` / `custom`), upload a kubeconfig, run a bounded live connection test, and view cluster details — without a backend restart. Adds the `cluster_connection_config` and append-only `cluster_config_events` tables (migration `f2a7c4e9b1d3`), an effective-config resolver caching one client per `(scope_key, config_version)`, and the `infrastructure` RBAC resource. The `KUBERNETES_*` env vars become a bootstrap fallback seeded into the platform-default scope.
- Login audit trail — `last_login_at` and `last_login_ip` recorded on every successful authentication.

### 🔄 Changed

- Access token expiry reduced from 30 to 15 minutes.
- Refresh tokens are now `HttpOnly` cookies backed by Redis, with family-based rotation and reuse detection (a replayed token revokes the whole family).
- CORS hardened — explicit origin / method / header allowlists with `allow_credentials=True`.
- Application lifecycle migrated from `@app.on_event` handlers to the FastAPI `lifespan` context manager.
- `GET /health` now probes PostgreSQL and the auth Redis, reporting `healthy` / `degraded` / `unhealthy`.
- **CD bump now pushes via a deploy key.** With branch protection active, the automated `chore(deploy):` overlay bump pushes over SSH using a read-write **deploy key** (`CD_PUSH_DEPLOY_KEY`) — a ruleset bypass actor — instead of a `GITHUB_TOKEN`/PAT direct push (neither bypasses on a personal repo). Human pushes stay gated behind PR + CI.

### 🔒 Security

- **etcd encryption-at-rest ENABLED** (operator action, 2026-06-27) — `aescbc` encryption is active on the live cluster; all three apiserver operators report `Encrypted: EncryptionCompleted`. A copy of the etcd datastore (backup, disk image, stolen volume) no longer yields `Secret` plaintext. See `backend/openshift/SECURITY-RUNBOOK.md` §1.
- **Merge gating ENABLED** (2026-06-27) — a repository ruleset (`merge-gating`) protects `main` and `develop`: require a pull request, require the 4 always-on CI status checks, and block force-push / branch deletion. Bypass actors are repository admins (emergency override) and the CD deploy key (automated bump). This makes a green CI a hard precondition for merging, layered on top of the existing `cd.yml` `workflow_run` gate.

- Brute-force protection on `/auth/login` — sliding-window throttle, per email and per source IP.
- **Cluster credential encryption** — uploaded kubeconfig contents and custom bearer tokens (feature 002) are Fernet-encrypted at rest via the existing credential vault; read schemas are secret-free (`has_credentials: bool`). Custom `api_url` and kubeconfig `cluster.server` URLs are SSRF-validated, and every config change is recorded in the append-only `cluster_config_events` audit table.
- **Scan-on-deploy** — Trivy gates `cd.yml`, failing the deploy on a fixable HIGH/CRITICAL CVE *before* the image is pushed (`ignore-unfixed: true`, mirroring the pip-audit policy). A CycloneDX SBOM is retained per image. Base-image CVEs were cleared (`apt-get upgrade` in the backend runtime stage, `apk upgrade` in the frontend image); the `.trivyignore` now defers only build-tooling advisories (`wheel`, `jaraco.context`) — the former urllib3 block was removed once the dependency bump (below) moved urllib3 to the 2.x line.
- **Dependency security bumps — paramiko 3.4 → 5.0, kubernetes 28 → 31, urllib3 1.26 → 2.x.** The SSH connectors use only paramiko's stable high-level API (no DSA keys / `disabled_algorithms`) and the KubeVirt/migrator code only the stable `CoreV1`/`BatchV1`/`StorageV1`/`CustomObjects` surface, so both majors are drop-in. The kubernetes client is pinned to **31.x to match the live cluster** (OpenShift 4.18 = Kubernetes 1.31.5) rather than jumping ahead of the server. This lifts the old urllib3 `<2.0.0` cap, clearing the full advisory set the 1.26.x line could not — `paramiko CVE-2026-44405` and `urllib3 PYSEC-2026-141 / CVE-2025-50181 / CVE-2025-66418 / CVE-2025-66471 / CVE-2026-21441`. The pip-audit and `.trivyignore` allow-lists for these CVEs were deleted; `pip-audit --strict` now runs with no exceptions. Full test suite green against the bumped stack.
- **Least-privilege API ServiceAccount in-cluster** — added the bounded `shiftwise-api-cluster` ClusterRole/binding for the `shiftwise-api` SA: read on `namespaces` / `nodes` / `storageclasses` and manage on KubeVirt `virtualmachines` (+ read `virtualmachineinstances`). No `*` verbs; no access to Secrets, ConfigMaps, RBAC objects, or Deployments.

### 🐛 Fixed

- **Proxmox disk enumeration** — the converter matched config keys by prefix, so the `scsihw` controller (`virtio-scsi-single`) and `virtiofs0` were parsed as disks, spawning a phantom disk that failed every Proxmox migration with `ERR_DISK_NOT_FOUND`. Now matched by a bus+index pattern (`scsi0`, `virtio1`, …).
- **`DELETE /migrations/{id}` returned HTTP 500** when audit events referenced the migration — the ORM tried to nullify the NOT-NULL `migration_events.migration_id` and hit the append-only trigger. Now returns a clean **409** (audit retention; the trail is preserved); a migration with no events still deletes (204).
- **System-role permissions not reconciled** — `create_system_roles` only created roles when absent, so deployments seeded before the permission-matrix update kept stale grants (`user`/`viewer` could not read hypervisors). It now reconciles `permissions` for existing system roles on startup.
- **Adapter Job created before the tenant namespace existed** (404) — the orchestrator now ensures the tenant namespace before the Adapter stage (idempotent).
- **Adapter pod rejected by SCC** — the `nfs`-volume `shiftwise-populator` SCC was bound only to the control-plane SA; tenant namespaces now get a dedicated `shiftwise-populator` SA + SCC grant provisioned automatically.
- **Adapter `guestfs_launch failed`** — the libguestfs appliance could not start on the nodes; the fixup now forces the TCG software-emulation backend, requires a privileged pod, and makes the staged qcow2 writable for the arbitrary OpenShift UID.
- **Fresh-database initialization failed on PostgreSQL** — boolean columns (`roles.is_system_role`/`is_active`, `users.is_active`/`is_verified`/`is_superuser`) carried an integer `server_default` (`text("0"|"1")`), rendering `BOOLEAN DEFAULT 0` — accepted by SQLite but rejected by PostgreSQL (`DatatypeMismatch`). This broke `Base.metadata.create_all()` and therefore `bootstrap.py` / the `db-init` Job on a brand-new database. Now uses dialect-correct `false()` / `true()`; covered by a PostgreSQL-dialect DDL guard test.
- **Infrastructure page (feature 002 UI)** — the cluster health badge rendered no reason (a `degraded` / `unreachable` / `auth_failed` verdict gave no diagnostic), and the scope editor had no error state (a 403/5xx rendered a blank panel) and used a bare text loader. Now shows `health_reason` with a tooltip, an error callout on load failure, and a skeleton loader — consistent with the rest of the SPA.
- **Frontend table accessibility** — data-table column headers now carry `scope="col"` and every data table has an `aria-label`, so assistive technology associates each cell with its column header and announces what each table contains instead of a bare "table".
- **In-cluster connection test returned HTTP 403** — the Infrastructure "Test connection" probe (`list_namespace()` + `list_node()`) and the KubeVirt VM-dashboard endpoints failed for the `incluster` platform-default scope because the `shiftwise-api` SA only had a namespaced Role. Granting the `shiftwise-api-cluster` ClusterRole clears the 403 (the worker SA already had its own ClusterRole, so migrations themselves were unaffected). **Validated live (2026-06-27):** the probe returns 200 (server v1.31.5, namespace/node counts) against production.
- **Over-permissive populator SCC** — `populator-scc.yaml` declared `allowedVolumeTypes:`, which is **not** a field of `SecurityContextConstraints`. The typed API silently dropped it, leaving the canonical `volumes` field defaulted to **all** volume types — the SCC was far broader than the documented "clone restricted-v2, add only `nfs`" intent, *and* it produced a permanent Argo `OutOfSync` on the cluster-scoped SCC. Renamed to `volumes:` so the restriction actually applies; added `ignoreDifferences` on the SCC `users`/`groups` (the migrator appends a per-tenant populator SA at runtime, which git can't enumerate — and on the selfHeal staging App, Argo was stripping it mid-migration).
- **Deployed-stack manifest fixes** — the HostNetwork OpenShift Router was blocked by the default-deny `NetworkPolicy` (Route returned 503 on new pods): added the `policy-group.network.openshift.io/host-network` namespace selector to the backend/frontend ingress allow rules. Also: Flower crash-looped without the `shiftwise-credential-key` `envFrom` (added); Redis hit `CreateContainerConfigError` on missing `REDIS_*`/`CELERY_*` secret keys; and the production overlay was right-sized (HPA `minReplicas:1`/`maxReplicas:2`, frontend 1 replica, lower CPU requests) to fit the cluster's reserved capacity.

### 🧪 Dev / Demo

- **Convert-on-source SFTP transit bridge** (`CONVERTER_SOURCE_CONVERT_SFTP`, default **off**) — for local development where the worker can reach the source hypervisor but not the cluster NFS: converts and compresses the disk on the source node, then uploads the small qcow2 to the transit NFS over SSH (optionally via a bastion jump). The production in-cluster conversion path is unchanged.

### 🚧 In Development

- **Frontend SPA** — all pages built and **live-verified against a running backend** (real auth + data, 0 console errors, no overflow at 375px/1440px, focus-trapped drawers); accessibility hardened (table semantics, focus management, type-enforced icon-button labels). Only cluster-execution flows (running a migration end-to-end, the Infrastructure connection test) await live cluster access.
- **Windows guest support** — `virt-v2v --in-place` path in the Adapter for Windows guests (code wired + unit-tested; the worker image ships virtio-win behind an opt-in, license-gated `INSTALL_VIRTIO_WIN` build arg — a live Windows-source run is pending).
- **First production migration** — the deployed in-cluster worker can only migrate sources the cluster can route to; the nested-lab hypervisors (`172.16.100.x` / `192.168.20.x`) are laptop-only and remain on the local stack + dev SFTP bridge. A live run from the deployed app awaits a cluster-reachable vCenter.

---

## [1.0.0] — 2026-03-14

### ✨ Added

#### User Management
- Full CRUD operations for user accounts
- Multi-tenancy support with complete data isolation between organizations
- Tenant-scoped queries enforced at the CRUD layer

#### RBAC System
- Role-based access control with 4 predefined system roles:
  - `super_admin` — unrestricted platform access
  - `admin` — full tenant management (users, VMs, migrations)
  - `user` — read/write access to VMs and migrations
  - `viewer` — read-only access
- JSON-based permission matrix stored per role (`{resource: [actions]}`)
- Support for custom roles alongside system roles
- Permission enforcement via dependency injection (`deps.py`)

#### Authentication
- JWT-based authentication with access and refresh tokens
- Access token expiry: 30 minutes (configurable)
- Refresh token expiry: 7 days (configurable)
- Password hashing via bcrypt with 72-byte truncation safety
- Password strength validation (min 8 chars, mixed case + digits)

#### KubeVirt Client
- Kubernetes/OpenShift integration via `python-kubernetes`
- Three connection modes:
  - `kubeconfig` — local development using kubeconfig file
  - `incluster` — production pods using ServiceAccount
  - `custom` — external access with API URL + bearer token
- VM lifecycle operations against KubeVirt API

#### Database & Models
- PostgreSQL as primary data store
- SQLAlchemy 2.0 ORM (synchronous)
- Alembic for schema migrations
- Models: `User`, `Role`, `Hypervisor`, `VirtualMachine`, `Migration`
- Abstract `BaseModel` with integer auto-increment primary keys and audit timestamps

#### API Endpoints
- RESTful API v1 with 7 router groups
- Auto-generated Swagger UI (`/docs`) and ReDoc (`/redoc`)
- Global exception handler with debug mode support
- CORS middleware with configurable allowed origins
- Health check endpoint (`/health`)

#### Testing
- Comprehensive test suite covering all API endpoints
- Tests for user management, RBAC, KubeVirt client, and discovery service

#### Infrastructure
- OpenShift 4.18.1 compact cluster (3 control-plane/worker nodes, bare metal UPI)
- Bastion node with DNS (BIND), HAProxy, Apache HTTP, Chrony (NTP)
- NFS server with `nfs-client` StorageClass
- KubeVirt v1.4.1 installed with `virtctl`
- Domain: `migration.nextstep-it.com`

---

[Unreleased]: https://github.com/didaa16/ShiftWise/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/didaa16/ShiftWise/releases/tag/v1.0.0
