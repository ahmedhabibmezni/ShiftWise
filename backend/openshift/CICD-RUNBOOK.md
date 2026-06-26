# ShiftWise CI/CD Runbook

End-to-end continuous deployment: a `git push` builds, scans, and ships the
whole application to the OpenShift cluster, with HA and supply-chain controls.
This is the single source of truth tying together `ci.yml`, `cd.yml`,
`release.yml`, the kustomize overlays, and Argo CD. The deeper per-area notes
live in [`argocd/README.md`](argocd/README.md) and
[`buildconfigs/README.md`](buildconfigs/README.md).

> **Status (2026-06-24): LIVE.** The pipeline is activated end-to-end — `cd.yml`
> is on `main`, Argo CD runs in-cluster with automated sync on both Applications,
> and production is serving at `https://shiftwise.apps.migration.nextstep-it.com`
> (VPN-only; shared host `/` → frontend, `/api` → backend). CD now builds the
> migration **worker image** in addition to the backend/frontend images.

---

## 1. Architecture — why pull-based GitOps

The cluster API (`api.migration.nextstep-it.com:6443`) is on a **private on-prem
network behind a slow VPN**. A GitHub-hosted runner cannot reach it. So CI/CD
never runs `oc apply`. Instead:

- **GitHub Actions** (cloud) builds + scans + pushes images to Docker Hub and
  writes the desired image tag into git (the kustomize overlay).
- **Argo CD** (inside the cluster) watches git, pulls the change, and applies it.
  All cluster mutation is outbound-from-cluster; **no cluster credentials ever
  live in CI, and nothing inbound to the cluster is required.**

```
 push develop ─► ci.yml (tests) ─success─► cd.yml ─┐
 push main    ─► ci.yml (tests) ─success─► cd.yml ─┤
                                                   ├─ build backend + worker + frontend
                                                   ├─ Trivy scan  (fail HIGH/CRITICAL)
                                                   ├─ SBOM (CycloneDX, per image)
                                                   ├─ push  shiftwise-{backend,backend-worker,frontend}:sha-XXXXXXX
                                                   ├─ kustomize set image → overlays/{staging|production}
                                                   └─ commit "chore(deploy): …" → {develop|main}
                                                         │
                                                         ▼  (egress only)
                                              Argo CD in-cluster ── auto-sync ──► namespace
                                                  develop → shiftwise-staging
                                                  main    → shiftwise (production)
```

**Image scheme.** `docker.io/dida1609/shiftwise-backend` backs backend /
celery-worker / flower / db-init; `shiftwise-frontend` is the SPA. A third image,
`shiftwise-backend-worker` (built from `backend/Dockerfile.worker` — `FROM` the
backend image + `qemu-utils` + `libguestfs-tools` + `linux-image-amd64`), backs
the converter / adapter / populator **Kubernetes Jobs** that need the migration
tooling. The migration Job image refs (`CONVERTER_CONTAINER_IMAGE`,
`ADAPTER_IMAGE`, `MIGRATOR_POPULATOR_IMAGE`) point at it with
`imagePullPolicy: Always`. Images are tagged with the immutable `sha-<7charSHA>`
of the commit they were built from (plus a rolling `<branch>` tag for humans).
Overlays are pinned to the `sha-` tag, so every deploy is deterministic and
rollback is a git revert.

---

## 2. The three workflows

| Workflow | Trigger | Does |
| -------- | ------- | ---- |
| `ci.yml` | push / PR to develop, main | Quality gate: ruff, pytest (CI-safe + postgres-only), pip-audit, frontend typecheck/vitest/audit, ML artifact integrity. No deploy. |
| `cd.yml` | `ci` **completed successfully** on develop or main | Build → Trivy → SBOM → push `sha-` images → bump the matching overlay → commit. Argo does the rest. |
| `release.yml` | push tag `v*` | Mints immutable, human-named `vX.Y.Z` images for archival / rollback targets. **Does not deploy.** |

**CD is gated on CI** via `workflow_run`: CD cannot run unless CI concluded
`success` on that exact commit. A red suite can never ship.

**Loop-breaker.** CD's overlay-bump commit is prefixed `chore(deploy):`. CD's
`if:` excludes that prefix, so the bump commit's own CI run does not re-trigger a
deploy. Without this guard, sha-tagged images would loop forever (each bump is a
new commit → new sha → new image → new bump).

> ### ✅ One-time bootstrap (done): `cd.yml` reached the default branch
> GitHub only fires a `workflow_run` from the workflow file present on the
> repository's **default branch** (`main`). `cd.yml` is now on `main`, so CD is
> active for both `develop` (→ staging) and `main` (→ production). If you ever
> re-init the repo or rename the default branch, re-merge `cd.yml` to it.

---

## 3. Required GitHub configuration

**Repository secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Used by | Purpose |
| ------ | ------- | ------- |
| `DOCKER_USERNAME` | cd.yml, release.yml | Docker Hub push account (`dida1609` or a robot). |
| `DOCKER_PASSWORD` | cd.yml, release.yml | Docker Hub **access token** (not the account password). |
| `CI_FERNET_KEY` | release.yml quality-gate | A valid Fernet key so `Settings()` boots in the coverage gate. |

**Branch protection.** Because `main` → production is now automatic, the
production gate **is** `main`'s branch protection. Require PR review + passing CI
on `main`. If `main` (or `develop`) is protected against direct pushes, the CD
overlay-bump push is rejected — switch that branch's bump to a PR (see §7).

---

## 4. One-time cluster bootstrap (run over the VPN)

These run on the bastion (`10.9.21.150`) with `oc` logged in. CI never does this.

### 4.1 Install OpenShift GitOps (Argo CD)

```bash
oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-gitops-operator
  namespace: openshift-operators
spec:
  channel: latest
  name: openshift-gitops-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

This creates the Argo CD instance in `openshift-gitops`. Its
application-controller SA has cluster-admin, required because the overlays manage
a cluster-scoped `SecurityContextConstraints` (`populator-scc.yaml`).

### 4.2 (Private repo) register repo read credentials

```bash
oc -n openshift-gitops create secret generic shiftwise-repo \
  --from-literal=type=git \
  --from-literal=url=https://github.com/ahmedhabibmezni/ShiftWise.git \
  --from-literal=username=<github-user> \
  --from-literal=password=<github-PAT-repo-read>
oc -n openshift-gitops label secret shiftwise-repo \
  argocd.argoproj.io/secret-type=repository
```

### 4.3 Out-of-band secrets in EACH target namespace

Argo applies manifests but **not** secrets (git-ignored by design). For each of
`shiftwise` (prod) and `shiftwise-staging`:

```bash
NS=shiftwise            # then repeat with NS=shiftwise-staging
oc new-project $NS 2>/dev/null || true

# App secrets + config (fill from secrets.example.yaml)
oc apply -n $NS -f secrets.local.yaml

# Credential vault key — backend/worker/db-init crash at boot without it
oc -n $NS create secret generic shiftwise-credential-key \
  --from-literal=SHIFTWISE_FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

### 4.4 Docker Hub pull secret (avoid anonymous rate-limit)

Nodes pulling `docker.io` anonymously hit `toomanyrequests`. In each namespace:

```bash
oc -n $NS create secret docker-registry dockerhub-pull \
  --docker-server=docker.io --docker-username=<user> --docker-password=<token>
for sa in shiftwise-api shiftwise-worker default; do
  oc -n $NS secrets link $sa dockerhub-pull --for=pull
done
```

### 4.5 Register the Argo Applications

```bash
oc apply -f argocd/application-staging.yaml
oc apply -f argocd/application-production.yaml
```

Staging auto-syncs from `develop`; production auto-syncs from `main`
(`selfHeal` off on prod — see §6).

---

## 5. Day-to-day: how a change ships

1. Open a PR into `develop`. CI runs (tests). Merge when green.
2. The push to `develop` runs CI again → on success CD builds/scans/pushes
   `sha-<sha>` images, bumps `overlays/staging`, commits to `develop`.
3. Argo CD syncs `shiftwise-staging` to the new digest. Verify there.
4. Promote: PR `develop` → `main`. On merge, the push to `main` runs CI → CD
   bumps `overlays/production`, commits to `main`, Argo syncs `shiftwise` (prod).

No manual `oc apply`, no manual image tag, no `oc rollout restart` — the new
`sha-` digest forces a fresh pull (unlike the old `:latest` + `IfNotPresent`
footgun, which never re-pulled a moved tag).

---

## 6. HA posture

| Tier | Replicas | HA controls |
| ---- | -------- | ----------- |
| backend (API) | 2 → HPA 2–6 | HPA on CPU 70%, PDB `maxUnavailable:1`, soft anti-affinity across nodes, readiness/liveness on `/health`. |
| celery-worker | 3 → HPA 3–8 | HPA on CPU 75%, PDB `maxUnavailable:1`, soft anti-affinity, Celery-ping probes. |
| frontend (SPA)| 2 (no HPA) | PDB `maxUnavailable:1`, soft anti-affinity. Static nginx — 2 is enough. |
| postgresql / redis | 1 | **No PDB** (a 1-replica `minAvailable:1` would block node drains). Single-replica by design; durability is the PVC (redis AOF, postgres PVC). True HA = an operator (CloudNativePG / Redis Sentinel) — tracked, not in scope. |

- **HPA ↔ GitOps:** the Argo Applications `ignoreDifferences` on
  `/spec/replicas` so the autoscaler owns replica count without Argo reverting it.
- **Anti-affinity is soft** (`preferred`): on a cluster with fewer schedulable
  nodes than replicas, pods co-locate rather than going Pending.
- **Worker scale-down is conservative** (600s window): CPU-based HPA can't see
  in-flight Celery tasks. Queue-depth autoscaling (KEDA) + graceful drain is the
  planned upgrade; until then a scaled-down worker may interrupt a task that
  Celery's retry/ack semantics then re-dispatch.

---

## 7. Promotion, rollback, recovery

| Action | How |
| ------ | --- |
| Deploy to staging | Push/merge to `develop` (automatic). |
| Promote to production | PR `develop` → `main`, merge (automatic). |
| Roll back | `git revert` the `chore(deploy):` bump commit on the branch → CI → CD reapplies the previous `sha-` digest. Or `argocd app rollback shiftwise-production <history-id>`. The old image still exists in Docker Hub (immutable tag). |
| Protected branch rejects CD push | Change the bump to a PR: have CD open a PR instead of pushing (use `peter-evans/create-pull-request`), then auto-merge. Document per branch. |
| Pin a named release | Bump the overlay image tag to a `release.yml`-minted `vX.Y.Z` via PR to the target branch. |
| Inspect / diff | `argocd app get shiftwise-production` · `argocd app diff shiftwise-production`. |

`db-init` is an immutable `Job`: a changed spec needs `Replace=true` or a manual
delete (mirrors `deploy.sh`). Keep it idempotent (it is).

---

## 8. Security posture

- **Scan-on-deploy:** Trivy fails CD on a fixable HIGH/CRITICAL CVE *before* the
  push — a vulnerable image never reaches the registry or the cluster.
  `ignore-unfixed:true` mirrors the pip-audit policy (don't block on unpatchable
  upstream advisories).
- **SBOM:** a CycloneDX bill of materials per image, retained 90 days as a build
  artifact, so a later CVE disclosure can be matched against what shipped.
- **Immutable digests:** `sha-` tags + git-pinned overlays = reproducible,
  auditable deploys. No `:latest` in the deploy path.
- **Pinned actions:** every GitHub Action is pinned to a 40-char commit SHA.
- **Least-privilege CI:** default `contents: read`; only the CD deploy job gets
  `contents: write` (to push the bump). No cluster creds in CI at all.
- **Network segmentation:** `network-policy.yaml` default-denies ingress and
  re-allows only the legitimate flows.
- **Follow-up (not yet wired):** image **signing** with cosign keyless
  (`id-token: write` + `sigstore/cosign-installer` pinned to a verified SHA),
  pushing signatures alongside each image, then an Argo/admission verify gate.
  Deferred deliberately rather than pinning an unverified action SHA.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| Push to develop/main, no CD run | `cd.yml` not on `main` yet (workflow_run needs the default-branch copy) — merge it to `main`. Or CI failed (CD is gated on CI success). |
| CD pushes but cluster unchanged | Argo CD not installed / Application not registered (§4), or Argo can't read the repo (private — register creds §4.2). `argocd app get <name>`. |
| Rollout `ImagePullBackOff` | Anonymous Docker Hub rate-limit — link `dockerhub-pull` to the runtime SAs (§4.4). |
| Pod `CrashLoopBackOff` at boot | Missing `shiftwise-credential-key` secret in that namespace (§4.3). |
| HPA `<unknown>` targets | metrics-server / cluster monitoring not exposing pod CPU; the Deployment must declare CPU `requests` (it does). |
| CD loops, re-deploying itself | The `chore(deploy):` guard was altered — CD must exclude its own bump commits. |
| Argo shows replicas OutOfSync | Confirm `ignoreDifferences` on `/spec/replicas` is present in the Application (HPA owns it). |
| Route returns 503 on a fresh rollout | The HostNetwork OpenShift Router is blocked by the default-deny `NetworkPolicy`. The backend/frontend ingress allow rules must carry the `policy-group.network.openshift.io/host-network` namespace selector (`network-policy.yaml`). |
| Infrastructure "Test connection" → HTTP 403 (incluster) | The `shiftwise-api` SA lacks the cluster-scoped grant. Apply the `shiftwise-api-cluster` ClusterRole/binding (`backend-deployment.yaml`). RBAC is server-side per request — no pod restart needed. |
| Flower `CrashLoopBackOff` at boot | Missing `shiftwise-credential-key` `envFrom` — Flower imports `Settings()` which requires `SHIFTWISE_FERNET_KEY`. |
| Postgres/Redis `Pending` (Insufficient cpu) | Nodes near reserved capacity — the production overlay right-sizes CPU requests + caps HPA (`minReplicas:1`/`maxReplicas:2`, frontend 1). |
| Migration Job `ErrImagePull` on `-worker` | The worker image tag in the Job image refs doesn't exist — confirm CD pushed `shiftwise-backend-worker:sha-<commit>` and the ConfigMap/overlay points at a real tag. |
