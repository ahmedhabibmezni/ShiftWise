#!/usr/bin/env bash
#
# One-shot deployment of ShiftWise on OpenShift.
#
# Idempotent: safe to re-run. Handles the db-init Job's immutability
# (re-applying a finished Job fails, so we delete-and-recreate).
#
# Pre-requisites:
#   - oc CLI logged in to the target cluster
#   - KUBECONFIG points at the right cluster
#   - The image referenced in *-deployment.yaml exists on the registry
#
# Usage:
#   ./deploy.sh             # deploy + wait for everything to be ready
#   ./deploy.sh --no-wait   # apply manifests and exit immediately
#
set -euo pipefail

NAMESPACE="${NAMESPACE:-shiftwise}"
TIMEOUT_DEPLOY="${TIMEOUT_DEPLOY:-300s}"
TIMEOUT_DBINIT="${TIMEOUT_DBINIT:-180s}"

NO_WAIT=false
[[ "${1:-}" == "--no-wait" ]] && NO_WAIT=true

cd "$(dirname "$0")"

# Préflight — le Secret shiftwise-secrets et le ConfigMap shiftwise-config
# ne sont PAS dans la kustomization (ils contiennent / dérivent de secrets et
# sont gérés hors-Git). Ils doivent exister avant l'apply, sinon les pods
# restent en CreateContainerConfigError. Voir secrets.example.yaml.
echo "==> [0/6] Checking prerequisites (shiftwise-secrets / shiftwise-config)"
if ! oc get secret shiftwise-secrets -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: Secret 'shiftwise-secrets' missing in namespace '$NAMESPACE'." >&2
  echo "       cp secrets.example.yaml secrets.local.yaml, fill it, then:" >&2
  echo "       oc apply -f secrets.local.yaml -n $NAMESPACE" >&2
  echo "       (see secrets.example.yaml — do NOT commit the filled file)" >&2
  exit 1
fi
if ! oc get configmap shiftwise-config -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: ConfigMap 'shiftwise-config' missing in namespace '$NAMESPACE'." >&2
  echo "       It is defined alongside the Secret in secrets.example.yaml." >&2
  exit 1
fi
# B-1 — la clé du vault Fernet vit dans son propre Secret, référencé par
# envFrom dans backend / celery-worker / db-init. SHIFTWISE_FERNET_KEY étant
# un champ Settings requis sans défaut, son absence fait crasher TOUS les pods
# au boot (ValidationError). On échoue vite ici plutôt que sur un CrashLoop.
if ! oc get secret shiftwise-credential-key -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: Secret 'shiftwise-credential-key' missing in namespace '$NAMESPACE'." >&2
  echo "       FERNET_KEY=\$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >&2
  echo "       oc -n $NAMESPACE create secret generic shiftwise-credential-key \\" >&2
  echo "         --from-literal=SHIFTWISE_FERNET_KEY=\"\$FERNET_KEY\"" >&2
  echo "       (see secrets.example.yaml — do NOT commit the real key)" >&2
  exit 1
fi

echo "==> [1/6] Applying kustomization to namespace '$NAMESPACE'"
# Layout canonique base/overlays (B-3) — la base est dans base/. Pour un
# déploiement avec vérification TLS K8s activée, utiliser plutôt l'overlay :
#   oc apply -k overlays/production
oc apply -k base

if $NO_WAIT; then
  echo "==> --no-wait set; skipping rollout waits."
  echo "    Run 'oc apply -f base/db-init-job.yaml -n $NAMESPACE' once postgres is Ready."
  exit 0
fi

echo "==> [2/6] Waiting for PostgreSQL (timeout: $TIMEOUT_DEPLOY)"
oc rollout status deployment/postgresql -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"

echo "==> [3/6] Running db-init Job (delete prior run if any)"
oc delete job db-init -n "$NAMESPACE" --ignore-not-found
oc apply -f base/db-init-job.yaml
oc wait --for=condition=complete job/db-init -n "$NAMESPACE" --timeout="$TIMEOUT_DBINIT"

echo "==> [4/6] Waiting for Redis"
oc rollout status deployment/redis -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"

echo "==> [5/6] Waiting for backend / worker / flower"
oc rollout status deployment/backend       -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"
oc rollout status deployment/celery-worker -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"
oc rollout status deployment/flower        -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"

echo "==> [6/6] Cluster ready"
oc get pods -n "$NAMESPACE"
echo
echo "Backend route:  https://$(oc get route backend -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
# Flower n'a plus de Route publique (durcissement G18). Accès opérateur :
echo "Flower (interne, basic-auth):  oc port-forward -n $NAMESPACE svc/flower 5555:5555  → http://localhost:5555"
