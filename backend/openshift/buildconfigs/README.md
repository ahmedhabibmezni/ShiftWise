# In-cluster image builds (OpenShift BuildConfig)

Build the ShiftWise images **on the cluster** — no Docker on the laptop
(Hyper-V is off, Docker Desktop is dead). The build pods clone the Git repo,
run a Docker-strategy build of the committed Dockerfiles, and push to the
internal OpenShift registry as ImageStreams.

This is the cluster-side alternative to `docker build` referenced in the
project notes (build on a cluster-side Linux box **or** via a BuildConfig).

## What gets built

| ImageStream             | Dockerfile                  | Contents                                                    |
| ----------------------- | --------------------------- | ----------------------------------------------------------- |
| `shiftwise-backend-api` | `backend/Dockerfile`        | Slim API/Flower/db-init base (no guest tooling)             |
| `shiftwise-backend`     | `backend/Dockerfile.worker` | API base **+** `qemu-img` + `libguestfs-tools` + kernel     |
| `shiftwise-frontend`    | `frontend/Dockerfile`       | nginx + built SPA                                           |

`shiftwise-backend` is the single image every backend workload (backend,
celery-worker, db-init, flower) **and** the adapter/populator Jobs run from —
it must carry the guest tooling. Its build is **chained** on
`shiftwise-backend-api` (`Dockerfile.worker` is `FROM ${API_IMAGE}`).

## Prerequisites

- `oc` logged in to the cluster, `KUBECONFIG` set, current project `shiftwise`.
- The OpenShift internal registry is up (it is — `nfs-client` storage, default).
- **Private repo only:** a Git auth secret so the build can clone:

  ```bash
  oc -n shiftwise create secret generic shiftwise-git-auth \
    --from-literal=username=<gh-user> \
    --from-literal=password=<gh-personal-access-token> \
    --type=kubernetes.io/basic-auth
  oc -n shiftwise annotate secret shiftwise-git-auth \
    'build.openshift.io/source-secret-match-uri-1=https://github.com/*'
  ```

  If the repo is **public**, delete the `sourceSecret:` block from each
  BuildConfig in `buildconfigs.yaml` before applying.

## Build

```bash
oc apply -n shiftwise -f backend/openshift/buildconfigs/buildconfigs.yaml

oc -n shiftwise start-build shiftwise-backend-api --follow
oc -n shiftwise start-build shiftwise-backend     --follow   # also auto-fires on api change
oc -n shiftwise start-build shiftwise-frontend    --follow
```

Windows guest support: rebuild the worker with the virtio-win ISO baked in
(after auditing the virtio-win license):

```bash
oc -n shiftwise patch bc/shiftwise-backend --type=json -p \
  '[{"op":"replace","path":"/spec/strategy/dockerStrategy/buildArgs/1/value","value":"true"}]'
oc -n shiftwise start-build shiftwise-backend --follow
```

## Make the deployment use the in-cluster images

The base manifests reference `docker.io/dida1609/shiftwise-backend:latest` and
`shiftwise-frontend:latest`. Repoint them at the internal registry with a
kustomize `images:` override — **no base edit required**. Add to your overlay
(`backend/openshift/overlays/<env>/kustomization.yaml`):

```yaml
images:
  - name: docker.io/dida1609/shiftwise-backend
    newName: image-registry.openshift-image-registry.svc:5000/shiftwise/shiftwise-backend
    newTag: latest
  - name: docker.io/dida1609/shiftwise-frontend
    newName: image-registry.openshift-image-registry.svc:5000/shiftwise/shiftwise-frontend
    newTag: latest
```

Then `oc apply -k backend/openshift/overlays/<env>` (or `./deploy.sh` if it
points at the overlay).

> **`:latest` + `imagePullPolicy: IfNotPresent` caveat.** The deployments pin
> `IfNotPresent`, so a node that already cached `:latest` will NOT pull a freshly
> built `:latest`. After a rebuild, force a rollout:
> `oc -n shiftwise rollout restart deploy/shiftwise-backend deploy/shiftwise-celery-worker deploy/shiftwise-flower deploy/shiftwise-frontend`
> (the build produces a new image digest; the restart re-resolves the tag). For
> deterministic deploys, consume the ImageStream by digest instead of `:latest`.

## Alternative: push to Docker Hub

To keep the manifests' `docker.io/...` references untouched, change each
BuildConfig `output.to` to a `DockerImage` and attach a push secret:

```yaml
output:
  to:
    kind: DockerImage
    name: docker.io/dida1609/shiftwise-backend:latest
  pushSecret:
    name: dockerhub-push   # oc create secret docker-registry dockerhub-push ...
```

This needs cluster egress to `docker.io` (the same path used to pull
`postgres`/`redis`) and the registry push credentials. The internal-registry
route above avoids both and is preferred for in-cluster builds.

## Status / troubleshooting

```bash
oc -n shiftwise get builds
oc -n shiftwise logs -f bc/shiftwise-backend
oc -n shiftwise get istag        # resolved digests
```

> **Not yet validated on the live cluster.** The Dockerfiles build locally as a
> design but these BuildConfigs have not been run against the cluster (no
> cluster access from the dev host). Treat the first run as a smoke test —
> watch the build logs and the resulting `istag` digests.
