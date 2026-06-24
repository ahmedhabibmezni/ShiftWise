# GitOps deployment (OpenShift GitOps / Argo CD)

Pull-based delivery for ShiftWise. Argo CD runs **inside** the cluster and
reconciles the kustomize overlays from this repo. CI never touches the cluster
API — which is the point: `api.migration.nextstep-it.com:6443` is on a private
on-prem network behind a slow VPN, unreachable from GitHub-hosted runners.

```
push vX.Y.Z ─► release.yml ─► build+push images ─► kustomize edit set image
                                                          │ (commit to develop)
                                                          ▼
                                              Argo CD (in-cluster) ── sync ──► staging
                                              (production: manual promotion via PR to main)
```

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

Staging auto-syncs from `develop`. Production stays OutOfSync until promoted.

## Day-2

| Action | How |
| ------ | --- |
| Deploy to staging | Push a `vX.Y.Z` tag → release.yml bumps the staging overlay tag on `develop` → Argo auto-syncs. |
| Promote to production | PR to `main` bumping `overlays/production` image tags → merge → `argocd app sync shiftwise-production` (or click Sync). |
| Inspect / diff | `argocd app get shiftwise-production` · `argocd app diff shiftwise-production`. |
| Rollback | `argocd app rollback shiftwise-production <history-id>`, or revert the git commit. |

## Notes / known gaps

- The runtime Job image refs (`CONVERTER_CONTAINER_IMAGE`, `ADAPTER_IMAGE`,
  `MIGRATOR_POPULATOR_IMAGE` in the `shiftwise-config` ConfigMap) are plain
  config strings, **not** kustomize image fields, so `kustomize edit set image`
  does **not** retag them — they track whatever the ConfigMap says (currently
  `:latest`). For fully-pinned releases, bump those three values in the overlay
  too (a `configMapGenerator` patch or a JSON6902 patch on the ConfigMap).
- `db-init` is a `Job` (immutable spec). Re-syncing an unchanged Job is a no-op,
  but a changed Job spec needs `Replace=true` or a manual delete — Argo flags it
  as SyncFailed otherwise. Keep db-init idempotent (it is) and delete it before
  a spec change, mirroring `deploy.sh`'s delete-and-recreate.
