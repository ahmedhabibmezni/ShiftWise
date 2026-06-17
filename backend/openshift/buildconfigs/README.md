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
- A push target for the built images. **Two cases:**
  - **Internal registry available** → the `ImageStreamTag` outputs below work as-is.
  - **Internal registry disabled** (`oc get configs.imageregistry.operator.openshift.io/cluster -o jsonpath='{.spec.managementState}'` returns `Removed`, as on the current cluster) → either re-enable it (`managementState: Managed` + storage) or repoint each BuildConfig output to an external registry (Docker Hub). See "Pushing to Docker Hub" below — that is the path used in production on this cluster.
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

## Pushing to Docker Hub (the path used on this cluster)

The cluster's internal registry is `Removed`, and the deployments already pull
`docker.io/dida1609/...`, so the builds push straight to Docker Hub. Create a
push secret and repoint each BuildConfig output to a `DockerImage`:

```bash
oc -n shiftwise create secret docker-registry dockerhub-push \
  --docker-server=docker.io --docker-username=<user> --docker-password=<token>

oc -n shiftwise patch bc/shiftwise-backend-api --type merge -p '{"spec":{"output":{"to":{"kind":"DockerImage","name":"docker.io/dida1609/shiftwise-backend-api:latest"},"pushSecret":{"name":"dockerhub-push"}}}}'
# repeat for shiftwise-backend (also set the API_IMAGE build-arg to the docker.io api image) and shiftwise-frontend
```

**Two non-obvious requirements when the internal registry is `Removed`:**

1. **The build subsystem needs a docker secret on the `builder` SA** (normally
   auto-created by the integrated registry). Without it builds fail
   `New (CannotRetrieveServiceAccount: No docker secrets associated with build
   service account builder)`:
   ```bash
   oc -n shiftwise secrets link builder dockerhub-push --for=pull,mount
   ```
2. **Authenticated image pulls** — nodes pulling `docker.io` anonymously hit
   `toomanyrequests` (Docker Hub rate limit), both for build base images and the
   deployment rollout. Link the same secret as an imagePullSecret on the runtime
   SAs:
   ```bash
   for sa in shiftwise-api shiftwise-worker default; do
     oc -n shiftwise secrets link $sa dockerhub-push --for=pull
   done
   ```

This needs cluster egress to `docker.io` (the same path used to pull
`postgres`/`redis`).

## Status / troubleshooting

```bash
oc -n shiftwise get builds
oc -n shiftwise logs -f bc/shiftwise-backend
oc -n shiftwise get istag        # resolved digests
```

> **Validated on the live cluster (2026-06-17).** All three images built via
> these BuildConfigs (api → worker chained → frontend) and pushed to Docker Hub;
> the full stack rolled out and `GET /health` reports `healthy`. The internal
> registry was `Removed`, so the Docker Hub path above (push secret + `builder`
> SA link + runtime-SA pull secrets) was required. Deploy by **image digest**,
> not `:latest` — `imagePullPolicy: IfNotPresent` will not re-pull a moved tag.
