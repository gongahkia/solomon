#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPDIR="$(mktemp -d)"
DB="$TMPDIR/load.redb"
PORT="${SHIBAHAMA_SERVICE_LOAD_PORT:-8888}"
BASE="http://127.0.0.1:$PORT"
REQUESTS="${SHIBAHAMA_SERVICE_LOAD_REQUESTS:-24}"
PARALLELISM="${SHIBAHAMA_SERVICE_LOAD_PARALLELISM:-6}"
API_KEY="service-load-smoke"
KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PID=""

cleanup() {
  code="$?"
  [[ -z "$PID" ]] || kill "$PID" >/dev/null 2>&1 || true
  [[ -z "$PID" ]] || wait "$PID" >/dev/null 2>&1 || true
  rm -rf "$TMPDIR"
  exit "$code"
}
trap cleanup EXIT

cd "$ROOT"
SHIBAHAMA_ENCRYPTION_KEY="$KEY" cargo run -q -p shibahama-cli -- serve \
  --path "$DB" --dimensions 2 --api-key "$API_KEY" --namespace service-load --bind "127.0.0.1:$PORT" >"$TMPDIR/server.log" 2>&1 &
PID=$!
for _ in {1..80}; do
  curl -fsS "$BASE/healthz" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS "$BASE/healthz" >/dev/null 2>&1 || { cat "$TMPDIR/server.log" >&2; exit 1; }

write_one() {
  local index="$1"
  curl -fsS -X POST "$BASE/write" \
    -H 'content-type: application/json' \
    -H "x-api-key: $API_KEY" \
    -H 'x-shibahama-namespace: service-load' \
    -H 'x-shibahama-scope-visibility: repository' \
    --data "{\"content\":\"load memory $index\",\"vector\":[1,0],\"source_kind\":\"agent\",\"source_ref\":\"load/$index\",\"ingested_by\":\"load-agent-$((index % 3))\",\"valid_from_unix\":0,\"ingested_at_unix\":0,\"scope\":{\"repository\":\"service-load\",\"team\":null,\"visibility\":\"repository\"}}" >/dev/null
}
export -f write_one
export BASE API_KEY
seq 1 "$REQUESTS" | xargs -n1 -P "$PARALLELISM" bash -c 'write_one "$0"'
count="$(curl -fsS "$BASE/inspect" -H "x-api-key: $API_KEY" -H 'x-shibahama-namespace: service-load' -H 'x-shibahama-scope-visibility: repository' | python3 -c 'import json,sys; print(json.load(sys.stdin)["memory_count"])')"
[[ "$count" == "$REQUESTS" ]] || { echo "expected $REQUESTS memories, got $count" >&2; exit 1; }
printf 'service-load-smoke requests=%s parallelism=%s memory_count=%s\n' "$REQUESTS" "$PARALLELISM" "$count"
