#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${SHIBAHAMA_CONTAINER_IMAGE:-shibahama:ci}"
container="shibahama-container-smoke-$$"
api_key="container-smoke-api-key"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
bootstrap_secret="container-smoke-bootstrap-secret-0001"
recovery_secret="container-smoke-recovery-secret-0001"

cleanup() {
  docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker image inspect "$image" >/dev/null 2>&1; then
  SHIBAHAMA_CONTAINER_IMAGE="$image" "$ROOT/scripts/ci/container-build.sh"
fi

if docker run --rm \
  --env SHIBAHAMA_API_KEY="$api_key" \
  --env SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET="$bootstrap_secret" \
  --env SHIBAHAMA_ADMIN_RECOVERY_SECRET="$recovery_secret" \
  --env SHIBAHAMA_DIMENSIONS=2 \
  --env SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" \
  --env SHIBAHAMA_UNDOCUMENTED=1 \
  "$image" >/dev/null 2>&1; then
  echo "container accepted undocumented configuration" >&2
  exit 1
fi

docker run --detach \
  --name "$container" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --publish 127.0.0.1::8765 \
  --env SHIBAHAMA_API_KEY="$api_key" \
  --env SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET="$bootstrap_secret" \
  --env SHIBAHAMA_ADMIN_RECOVERY_SECRET="$recovery_secret" \
  --env SHIBAHAMA_DIMENSIONS=2 \
  --env SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" \
  "$image" >/dev/null

test "$(docker inspect --format '{{.Config.User}}' "$container")" = "65532:65532"
for _ in {1..80}; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
  if [[ "$health" == healthy ]]; then
    break
  fi
  if [[ "$health" == unhealthy ]]; then
    docker logs "$container" >&2 || true
    exit 1
  fi
  sleep 0.25
done
test "$health" = healthy

address="$(docker port "$container" 8765/tcp | head -n 1)"
bootstrap="$(curl -fsS -X POST \
  -H "x-api-key: $api_key" \
  -H "x-shibahama-bootstrap-secret: $bootstrap_secret" \
  -H 'x-shibahama-namespace: container-smoke' \
  "http://$address/admin/bootstrap")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"initialized": True}' "$bootstrap"
ready="$(curl -fsS \
  -H "x-api-key: $api_key" \
  -H 'x-shibahama-namespace: container-smoke' \
  -H 'x-shibahama-scope-visibility: repository' \
  "http://$address/readyz")"
python3 -c 'import json,sys
record = json.loads(sys.argv[1])
assert record["status"] == "ready"
assert record["namespace"] == "container-smoke"' "$ready"
