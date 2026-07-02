#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
trap 'rm -rf "$tmpdir"; if [[ -n "${server_pid:-}" ]]; then kill "$server_pid" 2>/dev/null || true; fi' EXIT

db="$tmpdir/server-smoke.redb"
bind="${SHIBAHAMA_SERVER_SMOKE_BIND:-127.0.0.1:8876}"
base="http://${bind}"
api_key="smoke"
namespace="smoke"

cd "$ROOT"

cargo run -q -p shibahama-cli -- serve \
  --path "$db" \
  --dimensions 2 \
  --api-key "$api_key" \
  --namespace "$namespace" \
  --bind "$bind" >/tmp/shibahama-server-smoke.log 2>&1 &
server_pid=$!

ready=false
for _ in {1..40}; do
  if curl -fsS -H "x-api-key: ${api_key}" -H "x-shibahama-namespace: ${namespace}" "${base}/readyz" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 0.25
done

if [[ "$ready" != true ]]; then
  cat /tmp/shibahama-server-smoke.log >&2 || true
  exit 1
fi

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"

  if [[ -n "$body" ]]; then
    curl -fsS \
      -X "$method" \
      -H "content-type: application/json" \
      -H "x-api-key: ${api_key}" \
      -H "x-shibahama-namespace: ${namespace}" \
      --data "$body" \
      "${base}${path}"
  else
    curl -fsS \
      -X "$method" \
      -H "x-api-key: ${api_key}" \
      -H "x-shibahama-namespace: ${namespace}" \
      "${base}${path}"
  fi
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value = value[part]
print(value)' "$field"
}

item_json="$(request POST /write '{"content":"Server smoke memory","vector":[1,0],"source_kind":"user","source_ref":"server-smoke","valid_from_unix":0,"ingested_at_unix":0}')"
memory_id="$(json_field id <<<"$item_json")"

request POST /timeline '{"query_vector":[1,0],"top_k":1,"as_of_unix":0}' >/dev/null
request POST /reinforce "{\"memory_id\":\"${memory_id}\",\"outcome\":\"cited\"}" >/dev/null
request POST /challenge "{\"memory_id\":\"${memory_id}\",\"reason\":\"server smoke challenge\"}" >/dev/null
request POST /affirm "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request POST /pin "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request POST /unpin "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request POST /correct "{\"memory_id\":\"${memory_id}\",\"proposed_content\":\"Server smoke corrected memory\"}" >/dev/null
request POST /consolidate '{"now_unix":86400}' >/dev/null
request GET /events >/dev/null
request GET "/audit/${memory_id}" >/dev/null
request GET /tideline/snapshot >/dev/null

project_json="$(request POST /graph/entities '{"entity_type":"Project","label":"Server Smoke Project","stable_key":"project:server-smoke","attributes":{"scope":"server-smoke"},"valid_from_unix":0,"ingested_at_unix":0}')"
project_id="$(json_field id <<<"$project_json")"
claim_json="$(request POST /graph/entities '{"entity_type":"Claim","label":"Server Smoke Claim","stable_key":"claim:server-smoke","attributes":{"scope":"server-smoke"},"valid_from_unix":0,"ingested_at_unix":0}')"
claim_id="$(json_field id <<<"$claim_json")"
relation_json="$(request POST /graph/relations "{\"relation_type\":\"supports\",\"from_entity\":\"${project_id}\",\"to_entity\":\"${claim_id}\",\"memory_id\":\"${memory_id}\",\"attributes\":{\"scope\":\"server-smoke\"},\"valid_from_unix\":0,\"ingested_at_unix\":0}")"
relation_id="$(json_field id <<<"$relation_json")"

request GET "/graph/entities/${project_id}" >/dev/null
request GET "/graph/relations/${relation_id}" >/dev/null
request GET /graph?as_of_unix=0 >/dev/null
request POST /graph/traverse "{\"start_entity\":\"${project_id}\",\"max_hops\":1,\"as_of_unix\":0}" >/dev/null
request DELETE "/graph/relations/${relation_id}?valid_to_unix=10" >/dev/null
request DELETE "/graph/entities/${claim_id}?valid_to_unix=10" >/dev/null

echo "server smoke passed"
