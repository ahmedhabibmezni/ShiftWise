# ShiftWise — OpenShift Security Runbook

Operator-facing security tasks for the ShiftWise deployment. These are
**cluster-level operations**, not application code — they cannot be shipped
in this repository and must be performed by a cluster administrator against
the target OpenShift cluster (`api.migration.nextstep-it.com:6443`).

This runbook covers the audit finding **G7**: the ShiftWise database
password, Redis password and JWT `SECRET_KEY` live in a Kubernetes `Secret`
(`shiftwise-secrets`). A Kubernetes `Secret` is **base64-encoded, not
encrypted** — anyone able to read the object, or anyone with read access to
the etcd datastore backing it, recovers the plaintext. The mitigations below
close that gap.

---

## 1. Enable etcd encryption-at-rest (primary G7 fix)

> **STATUS: ENABLED (2026-06-27).** `aescbc` encryption is active on the live
> cluster. All three operators report `Encrypted: EncryptionCompleted`
> (kube-apiserver, openshift-apiserver, authentication/OAuth). The steps below
> are retained as the procedure / for cluster rebuilds. Verify current state
> with `oc get apiserver cluster -o jsonpath='{.spec.encryption.type}'` (→
> `aescbc`) and the per-operator `Encrypted` conditions in step 3.

By default OpenShift stores `Secret` objects in etcd in plaintext (base64).
Encrypting etcd at rest means a copy of the etcd database — a disk image, a
backup, a stolen volume — does not yield the secrets.

This is a documented, supported OpenShift operation. It is **not reversible
into the repo**; an operator runs it once per cluster.

### Steps

1. Confirm you have `cluster-admin` and a healthy cluster:

   ```bash
   oc get clusteroperator kube-apiserver
   oc whoami --show-context
   ```

2. Enable encryption by patching the `APIServer` resource. `aescbc` is the
   broadly-available cipher; `aesgcm` is also supported on current 4.x —
   pick per the OpenShift docs for the running version (cluster is 4.18.1):

   ```bash
   oc patch apiserver cluster --type=merge \
     -p '{"spec":{"encryption":{"type":"aescbc"}}}'
   ```

3. Encryption rolls out asynchronously. The kube-apiserver, then the
   openshift-apiserver, then the OAuth apiserver each re-encrypt their
   resources. Watch for completion (can take 20-30 min):

   ```bash
   oc get openshiftapiserver -o=jsonpath='{range .items[0].status.conditions[?(@.type=="Encrypted")]}{.reason}{"\n"}{.message}{"\n"}{end}'
   oc get kubeapiserver      -o=jsonpath='{range .items[0].status.conditions[?(@.type=="Encrypted")]}{.reason}{"\n"}{.message}{"\n"}{end}'
   ```

   Both must report `reason: EncryptionCompleted`.

4. After enabling encryption, **re-write the existing Secrets** so the
   already-stored copies are re-encrypted (newly enabled encryption only
   covers writes that happen after rollout):

   ```bash
   oc get secret shiftwise-secrets -n shiftwise -o yaml | oc replace -f -
   ```

> Encryption keys are managed and rotated by OpenShift itself. To force a
> key rotation, bump `spec.encryption` (e.g. toggle the cipher) per the
> OpenShift docs — do not hand-edit etcd.

### Verification

A `Secret` read through `oc` always shows decrypted data (the apiserver
decrypts on the way out) — that does **not** prove etcd is encrypted. To
verify, an operator with etcd access reads the raw value:

```bash
# On a control-plane node, inside the etcd pod:
oc rsh -n openshift-etcd <etcd-pod>
etcdctl get /kubernetes.io/secrets/shiftwise/shiftwise-secrets | hexdump -C | head
```

Encrypted output is prefixed with `k8s:enc:aescbc:v1:` (or `aesgcm`).
Plaintext output would show readable base64 — that means encryption is not
yet in effect.

---

## 2. Tighten RBAC around the Secret

Encryption-at-rest does not stop a principal that can already call
`get secret shiftwise-secrets`. Reduce who can:

- **Audit current readers.** List every subject with `get`/`list` on
  Secrets in the `shiftwise` namespace:

  ```bash
  oc policy who-can get secret -n shiftwise
  oc policy who-can list secret -n shiftwise
  ```

  Anything other than the cluster admins and the ShiftWise pod
  ServiceAccounts is suspect.

- **Do not grant the broad `view` / `edit` / `admin` cluster roles** to
  ShiftWise users — `view` includes Secret read in many configurations.
  Use a project-scoped Role that excludes `secrets`.

- **The application ServiceAccount** needs `shiftwise-secrets` only as an
  `envFrom`/`secretKeyRef` mount — the kubelet reads it on the pod's
  behalf; the SA itself does **not** need a `get secret` RBAC verb. Verify
  no Role/RoleBinding grants the app SA standing Secret-read access.
  `worker-rbac.yaml` in this directory is the worker's RBAC — confirm it
  grants no `secrets` verbs (it should not).

- **Restrict `oc rsh` / `oc exec`** into ShiftWise pods. A shell in a pod
  can read the mounted Secret from the process environment or
  `/var/run/secrets`. `exec` is gated by the `pods/exec` subresource verb —
  keep it off non-admin roles.

---

## 3. Move to a real secret manager (recommended next step)

A Kubernetes `Secret` — even encrypted at rest — is still a long-lived
plaintext credential the moment a pod mounts it, and it has no rotation,
no leasing and no audit trail of access. For a production posture,
externalise the secrets:

- **External Secrets Operator (ESO)** — syncs from HashiCorp Vault, AWS/GCP
  Secrets Manager, etc. into a Kubernetes `Secret` the app still consumes
  unchanged. Lowest-friction option: no application code change.
- **HashiCorp Vault** with the Vault Agent Injector — secrets delivered to
  the pod filesystem, short-lived, with dynamic DB credentials and a full
  access audit log. This is the option already named as the future target
  in `CLAUDE.md` (hypervisor-credential storage).
- **Sealed Secrets** — lets the encrypted secret be committed to Git safely
  (the controller holds the only decryption key). Solves the
  "secret cannot be in Git" constraint but **not** rotation or leasing.

`secrets.example.yaml` in this directory already flags this: in production
the filled secrets file should never be `oc apply`'d from disk — it should
be delivered by one of the mechanisms above.

### Credential rotation (do this regardless)

`CLAUDE.md` records that `.env` with real credentials is in Git history
(finding GIT2). Encryption-at-rest does nothing for a credential already
leaked into history. Independently of the steps above:

1. Rotate `DATABASE_PASSWORD`, `REDIS_PASSWORD` and `SECRET_KEY` to fresh
   values (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
2. Re-apply `shiftwise-secrets` with the new values and restart the
   dependent Deployments (`postgresql`, `redis`, `backend`,
   `celery-worker`, `flower`).
3. Note: rotating `SECRET_KEY` invalidates every issued JWT — all users are
   logged out. Schedule it during a maintenance window.
4. Purge the leaked `.env` from Git history (`git filter-repo`) — tracked
   separately as GIT2.

---

## Scope note

Items 1 and 2 are operational tasks an administrator performs on the live
cluster; there is no repository artifact for them by design — fabricating
cluster config here would be misleading. Item 3 is a deployment-architecture
decision. This runbook is the deliverable for audit finding **G7**; the
repo-side mitigations (Secret kept out of Git, `secrets.example.yaml`
template, no `secretGenerator` in `kustomization.yaml`) are already in
place — see findings G6 and G25.
