#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="$ROOT/deploy/helm/shibahama"
IMAGE="${SHIBAHAMA_CONTAINER_IMAGE:-shibahama:ci}"
CLUSTER="shibahama-helm-${GITHUB_RUN_ID:-$$}"
NAMESPACE="shibahama-smoke"
ENCRYPTION_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
API_KEY="helm-smoke-api-key"
PORT=18765
FORWARD_PID=""

cleanup() {
  [[ -z "$FORWARD_PID" ]] || kill "$FORWARD_PID" >/dev/null 2>&1 || true
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

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
helm upgrade --install shibahama "$CHART" --namespace "$NAMESPACE" \
  --set image.repository="${IMAGE%:*}" \
  --set image.tag="${IMAGE##*:}" \
  --set image.pullPolicy=IfNotPresent \
  --set secrets.existingSecret=shibahama-secrets
kubectl -n "$NAMESPACE" rollout status deployment/shibahama-shibahama --timeout=120s
kubectl -n "$NAMESPACE" port-forward service/shibahama-shibahama "$PORT":8765 >/dev/null 2>&1 &
FORWARD_PID=$!
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
    exit 0
  fi
  sleep 0.25
done
kubectl -n "$NAMESPACE" get pods -o wide >&2
kubectl -n "$NAMESPACE" logs deployment/shibahama-shibahama >&2 || true
exit 1
