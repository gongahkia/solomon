#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="$ROOT/deploy/helm/shibahama"
IMAGE="${SHIBAHAMA_CONTAINER_IMAGE:-shibahama:ci}"
CLUSTER="shibahama-lifecycle-${GITHUB_RUN_ID:-$$}"
NAMESPACE="shibahama-lifecycle"
ENCRYPTION_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
API_KEY="lifecycle-smoke-api-key"

cleanup() {
  status="$?"
  if [[ "$status" -ne 0 ]]; then
    kubectl -n "$NAMESPACE" get pods -o wide >&2 || true
    kubectl -n "$NAMESPACE" logs -l app.kubernetes.io/name=shibahama --all-containers >&2 || true
  fi
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

deploy() {
  local release="$1"
  local destroy_policy="$2"
  helm upgrade --install "$release" "$CHART" --namespace "$NAMESPACE" \
    --set image.repository="${IMAGE%:*}" \
    --set image.tag="${IMAGE##*:}" \
    --set image.pullPolicy=IfNotPresent \
    --set secrets.existingSecret=shibahama-secrets \
    --set storage.destroyPolicy="$destroy_policy"
  kubectl -n "$NAMESPACE" rollout status "deployment/$release-shibahama" --timeout=120s
}

docker info >/dev/null
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  SHIBAHAMA_CONTAINER_IMAGE="$IMAGE" "$ROOT/scripts/ci/container-build.sh"
fi
if ! kind get clusters | rg -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --wait 90s
fi
kind load docker-image "$IMAGE" --name "$CLUSTER"
kubectl create namespace "$NAMESPACE"
kubectl -n "$NAMESPACE" create secret generic shibahama-secrets \
  --from-literal=encryption-key="$ENCRYPTION_KEY" \
  --from-literal=api-key="$API_KEY"

deploy shibahama-preserve preserve
helm uninstall shibahama-preserve --namespace "$NAMESPACE" --wait --timeout=120s
kubectl -n "$NAMESPACE" get pvc shibahama-preserve-shibahama >/dev/null

deploy shibahama-erase erase
helm uninstall shibahama-erase --namespace "$NAMESPACE" --wait --timeout=120s
for _ in {1..40}; do
  if ! kubectl -n "$NAMESPACE" get pvc shibahama-erase-shibahama >/dev/null 2>&1; then
    exit 0
  fi
  sleep 0.25
done
echo 'erase destroy policy retained its persistent volume claim' >&2
exit 1
