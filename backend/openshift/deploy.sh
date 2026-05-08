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

echo "==> [1/6] Applying kustomization to namespace '$NAMESPACE'"
oc apply -k .

if $NO_WAIT; then
  echo "==> --no-wait set; skipping rollout waits."
  echo "    Run 'oc apply -f db-init-job.yaml -n $NAMESPACE' once postgres is Ready."
  exit 0
fi

echo "==> [2/6] Waiting for PostgreSQL (timeout: $TIMEOUT_DEPLOY)"
oc rollout status deployment/postgresql -n "$NAMESPACE" --timeout="$TIMEOUT_DEPLOY"

echo "==> [3/6] Running db-init Job (delete prior run if any)"
oc delete job db-init -n "$NAMESPACE" --ignore-not-found
oc apply -f db-init-job.yaml
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
echo "Flower route:   https://$(oc get route flower  -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
