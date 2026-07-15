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
BOOTSTRAP_SECRET="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
RECOVERY_SECRET="abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
PORT=18765
FORWARD_PID=""

cleanup() {
  status="$?"
  if [[ "$status" -ne 0 ]]; then
    kubectl -n "$NAMESPACE" get pods -o wide >&2 || true
    kubectl -n "$NAMESPACE" logs deployment/shibahama-shibahama >&2 || true
  fi
  [[ -z "$FORWARD_PID" ]] || kill "$FORWARD_PID" >/dev/null 2>&1 || true
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  exit "$status"
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
  --from-literal=api-key="$API_KEY" \
  --from-literal=admin-bootstrap-secret="$BOOTSTRAP_SECRET" \
  --from-literal=admin-recovery-secret="$RECOVERY_SECRET"
helm upgrade --install shibahama "$CHART" --namespace "$NAMESPACE" \
  --set image.repository="${IMAGE%:*}" \
  --set image.tag="${IMAGE##*:}" \
  --set image.pullPolicy=IfNotPresent \
  --set secrets.existingSecret=shibahama-secrets \
  --set secrets.adminBootstrapKey=admin-bootstrap-secret \
  --set secrets.adminRecoveryKey=admin-recovery-secret \
  --set policy.fullSemanticErasure=true
kubectl -n "$NAMESPACE" rollout status deployment/shibahama-shibahama --timeout=120s
kubectl -n "$NAMESPACE" port-forward service/shibahama-shibahama "$PORT":8765 >/dev/null 2>&1 &
FORWARD_PID=$!
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
    break
  fi
  sleep 0.25
done
base="http://127.0.0.1:$PORT"
headers=(-H "x-api-key: $API_KEY" -H 'x-shibahama-namespace: default' -H 'x-shibahama-scope-visibility: repository')
curl -fsS -X POST -H "x-api-key: $API_KEY" -H "x-shibahama-bootstrap-secret: $BOOTSTRAP_SECRET" "$base/admin/bootstrap" >/dev/null
memory_id="$(curl -fsS -X POST "${headers[@]}" -H 'content-type: application/json' --data '{"content":"helm lifecycle erased memory","vector":[1,0],"source_kind":"user"}' "$base/write" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
curl -fsS -X POST "${headers[@]}" -H 'content-type: application/json' --data "{\"memory_id\":\"$memory_id\",\"authorization_id\":\"helm-lifecycle-erase-0001\"}" "$base/erase" >/dev/null
helm upgrade shibahama "$CHART" --namespace "$NAMESPACE" --reuse-values --set policy.rateLimitBurst=31
kubectl -n "$NAMESPACE" rollout status deployment/shibahama-shibahama --timeout=120s
kill "$FORWARD_PID" >/dev/null 2>&1 || true
kubectl -n "$NAMESPACE" port-forward service/shibahama-shibahama "$PORT":8765 >/dev/null 2>&1 &
FORWARD_PID=$!
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl -fsS "${headers[@]}" "$base/events" | python3 -c 'import json,sys; assert "memory_semantically_erased" in {event["kind"] for event in json.load(sys.stdin)["events"]}'
exit 0
