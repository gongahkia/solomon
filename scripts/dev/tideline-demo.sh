#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${SHIBAHAMA_DEMO_DB:-/tmp/shibahama-demo.redb}"
API_KEY="${SHIBAHAMA_DEMO_API_KEY:-dev}"
NAMESPACE="${SHIBAHAMA_DEMO_NAMESPACE:-demo}"
BIND="${SHIBAHAMA_DEMO_BIND:-127.0.0.1:8765}"
PREFIX="shibahama-server:namespace=${NAMESPACE};"

cd "$ROOT"
rm -f "$DB"

cargo run -q -p shibahama-cli -- init --path "$DB" --dimensions 2 >/dev/null

write_memory() {
  local content="$1"
  local vector="$2"
  local ref="$3"
  cargo run -q -p shibahama-cli -- write \
    --path "$DB" \
    --dimensions 2 \
    --content "$content" \
    --vector "$vector" \
    --source-kind user \
    --source-ref "${PREFIX}${ref}" \
    --valid-from-unix 0 \
    --ingested-at-unix 0
}

id_from_json() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
}

first="$(write_memory "Demo endpoint is /v1/orders." "1,0" "endpoint-a" | id_from_json)"
second="$(write_memory "Demo endpoint is /v1/orders." "1,0.02" "endpoint-b" | id_from_json)"
stale="$(write_memory "Legacy queue owner is Sam." "0,1" "queue-old" | id_from_json)"

cargo run -q -p shibahama-cli -- reinforce --path "$DB" --memory-id "$first" --outcome cited >/dev/null
cargo run -q -p shibahama-cli -- reinforce --path "$DB" --memory-id "$second" --outcome cited >/dev/null
cargo run -q -p shibahama-cli -- challenge --path "$DB" --memory-id "$stale" --reason "owner changed in demo" >/dev/null
cargo run -q -p shibahama-cli -- correct \
  --path "$DB" \
  --memory-id "$stale" \
  --proposed-content "Legacy queue owner is Priya." \
  --reason "demo correction" >/dev/null
cargo run -q -p shibahama-cli -- consolidate --path "$DB" --now-unix 86400 >/dev/null

cargo run -q -p shibahama-cli -- serve \
  --path "$DB" \
  --dimensions 2 \
  --api-key "$API_KEY" \
  --unsafe-development-plaintext \
  --namespace "$NAMESPACE" \
  --bind "$BIND" &
server_pid=$!

cleanup() {
  kill "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "server: http://${BIND}"
echo "namespace: ${NAMESPACE}"
echo "api key: ${API_KEY}"

(
  cd tideline
  npm install --silent
  npm run dev
)
