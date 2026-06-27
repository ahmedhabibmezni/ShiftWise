# GitOps deployment (OpenShift GitOps / Argo CD)

Pull-based delivery for ShiftWise. Argo CD runs **inside** the cluster and
reconciles the kustomize overlays from this repo. CI never touches the cluster
API — which is the point: `api.migration.nextstep-it.com:6443` is on a private
on-prem network behind a slow VPN, unreachable from GitHub-hosted runners.

```
push develop ─► ci.yml ─► cd.yml ─► build+scan+push images ─► kustomize edit set image
push main    ─► ci.yml ─► cd.yml ─►                              │ (commit to same branch)
                                                                 ▼
                                              Argo CD (in-cluster, auto-sync) ──► develop → shiftwise-staging
                                                                                  main    → shiftwise (production)
```

> **State (2026-06-24): live.** Both Applications have automated sync enabled and
> are reconciling from git. `release.yml` (`v*` tags) still mints immutable
> `vX.Y.Z` images for archival / pinned rollback, but the day-to-day deploy path
> is the push-based `cd.yml` above (see `../CICD-RUNBOOK.md`).

## One-time setup

### 1. Install the OpenShift GitOps operator

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

This creates the default Argo CD instance in the `openshift-gitops` namespace.
Its application-controller ServiceAccount has cluster-admin, which is required
here because the overlays manage a **cluster-scoped** `SecurityContextConstraints`
(`populator-scc.yaml`). If you harden the controller's RBAC, it must retain
`securitycontextconstraints` get/list/create/update plus `namespaces` create.

### 2. (Private repo only) register repo credentials

If `github.com/ahmedhabibmezni/ShiftWise` is private, give Argo read access:

```bash
oc -n openshift-gitops create secret generic shiftwise-repo \
  --from-literal=type=git \
  --from-literal=url=https://github.com/ahmedhabibmezni/ShiftWise.git \
  --from-literal=username=<github-user> \
  --from-literal=password=<github-PAT-with-repo-read>
oc -n openshift-gitops label secret shiftwise-repo \
  argocd.argoproj.io/secret-type=repository
```

### 3. Create the out-of-band secrets in each target namespace

Argo deploys the manifests but **not** the secrets (they are git-ignored by
design — see `../secrets.example.yaml`). Before the first sync, in each of
`shiftwise` (prod) and `shiftwise-staging`:

```bash
NS=shiftwise   # then repeat with NS=shiftwise-staging
oc apply -n $NS -f secrets.local.yaml          # shiftwise-secrets + shiftwise-config (filled)
oc -n $NS create secret generic shiftwise-credential-key \
  --from-literal=SHIFTWISE_FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

> Argo creates the namespace itself (`CreateNamespace=true`), so create the
> secrets after the first (failed-on-missing-secret) sync, or pre-create the
> namespace with `oc new-project`.

### 4. Register the Applications

```bash
oc apply -f application-staging.yaml
oc apply -f application-production.yaml
```

Staging auto-syncs from `develop`; production auto-syncs from `main`.

## Day-2

| Action | How |
| ------ | --- |
| Deploy to staging | Push/merge to `develop` → CI → CD bumps `overlays/staging` → Argo auto-syncs `shiftwise-staging`. |
| Promote to production | PR `develop` → `main`, merge → CI → CD bumps `overlays/production` → Argo auto-syncs `shiftwise`. |
| Inspect / diff | `argocd app get shiftwise-production` · `argocd app diff shiftwise-production`. |
| Rollback | `git revert` the `chore(deploy):` bump commit (→ CI → CD reapplies the previous `sha-`), or `argocd app rollback shiftwise-production <history-id>`. |

## `ignoreDifferences`

Both Applications carry two `ignoreDifferences` entries:

- **`Deployment /spec/replicas`** — the HPA owns replica count at runtime; without
  this Argo (on selfHeal) would revert the autoscaled count.
- **`SecurityContextConstraints shiftwise-populator` `/users` + `/groups`** — the
  migrator's `ensure_populator_scc` appends a per-tenant populator SA
  (`system:serviceaccount:shiftwise-<tenant>:shiftwise-populator`) to the SCC at
  runtime on every migration into a fresh tenant namespace. Git can't enumerate
  live tenants, so without this the SCC shows perpetual drift — and on the
  selfHeal staging App, Argo would strip the tenant SA mid-migration.

> **SCC field note:** `populator-scc.yaml` declares `volumes:` (the canonical SCC
> field). It previously used `allowedVolumeTypes:`, which is **not** a valid SCC
> field — the typed API silently dropped it and `volumes` defaulted to *all*
> types, making the SCC far more permissive than intended *and* a permanent Argo
> diff. Fixed 2026-06-27.

## Staging is mothballed (2026-06-27)

The 3-node cluster cannot comfortably run the full prod **and** staging stacks
(CPU-bound). Staging is therefore **dormant**: its Argo App has **automated sync
disabled** and all `shiftwise-staging` Deployments are scaled to 0. The App shows
`OutOfSync` (live ≠ git) but `Healthy` (nothing running to be unhealthy) — this is
intentional. To revive staging: re-enable `syncPolicy.automated` on
`application-staging.yaml` (and free cluster CPU / right-size the staging overlay
first), then `oc apply` it.

## Notes / known gaps

- The runtime Job image refs (`CONVERTER_CONTAINER_IMAGE`, `ADAPTER_IMAGE`,
  `MIGRATOR_POPULATOR_IMAGE` in the `shiftwise-config` ConfigMap) point at the
  `shiftwise-backend-worker` image (built by `cd.yml` alongside the API/frontend
  images). They are plain config strings, **not** kustomize image fields, so
  `kustomize edit set image` does **not** retag them — they track whatever the
  ConfigMap says. For fully-pinned releases, bump those three values in the
  overlay too (a `configMapGenerator` patch or a JSON6902 patch on the ConfigMap).
- `db-init` is a `Job` (immutable spec). Re-syncing an unchanged Job is a no-op,
  but a changed Job spec needs `Replace=true` or a manual delete — Argo flags it
  as SyncFailed otherwise. Keep db-init idempotent (it is) and delete it before
  a spec change, mirroring `deploy.sh`'s delete-and-recreate.
