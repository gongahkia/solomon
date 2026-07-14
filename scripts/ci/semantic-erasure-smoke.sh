#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/semantic-erasure.redb"
bind="${SHIBAHAMA_SEMANTIC_ERASURE_BIND:-127.0.0.1:8877}"
base="http://${bind}"
api_key="semantic-erasure-smoke"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
namespace="semantic-erasure"
content="irreversible semantic erasure service payload"

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

start_server() {
  SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" cargo run -q -p shibahama-cli -- serve \
    --path "$db" \
    --dimensions 2 \
    --api-key "$api_key" \
    --namespace "$namespace" \
    --bind "$bind" \
    --full-semantic-erasure >"$tmpdir/server.log" 2>&1 &
  server_pid=$!

  for _ in {1..40}; do
    if curl -fsS -H "x-api-key: $api_key" -H "x-shibahama-namespace: $namespace" "$base/readyz" >/dev/null 2>&1; then
      return
    fi
    sleep 0.25
  done
  cat "$tmpdir/server.log" >&2 || true
  exit 1
}

stop_server() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  server_pid=""
}

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"

  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" \
      -H 'content-type: application/json' \
      -H "x-api-key: $api_key" \
      -H "x-shibahama-namespace: $namespace" \
      -H 'x-shibahama-scope-visibility: repository' \
      --data "$body" \
      "$base$path"
  else
    curl -fsS -X "$method" \
      -H "x-api-key: $api_key" \
      -H "x-shibahama-namespace: $namespace" \
      -H 'x-shibahama-scope-visibility: repository' \
      "$base$path"
  fi
}

json_field() {
  python3 -c 'import json,sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value = value[int(part)] if part.isdigit() else value[part]
print(value)' "$1"
}

cd "$ROOT"
start_server

invalid_erase_status="$(curl -sS -o "$tmpdir/invalid-erase.json" -w '%{http_code}' \
  -X POST \
  -H 'content-type: application/json' \
  -H "x-api-key: $api_key" \
  -H "x-shibahama-namespace: $namespace" \
  -H 'x-shibahama-scope-visibility: repository' \
  --data '{"memory_id":"00000000-0000-0000-0000-000000000000","authorization_id":""}' \
  "$base/erase")"
if [[ "$invalid_erase_status" != "400" ]]; then
  echo "invalid semantic-erasure authorization returned HTTP $invalid_erase_status" >&2
  exit 1
fi

item_json="$(request POST /write "{\"content\":\"$content\",\"vector\":[1,0],\"source_kind\":\"user\",\"source_ref\":\"semantic-erasure-smoke\",\"valid_from_unix\":0,\"ingested_at_unix\":0}")"
memory_id="$(json_field id <<<"$item_json")"
linked_entity_json="$(request POST /graph/entities "{\"memory_id\":\"$memory_id\",\"entity_type\":\"Claim\",\"label\":\"semantic-erasure graph payload\",\"stable_key\":\"claim:semantic-erasure\",\"attributes\":{\"evidence\":\"semantic-erasure graph attribute\"},\"valid_from_unix\":0,\"ingested_at_unix\":0}")"
linked_entity_id="$(json_field id <<<"$linked_entity_json")"
retained_entity_json="$(request POST /graph/entities '{"entity_type":"Project","label":"retained graph entity","stable_key":"project:retained-semantic-erasure","valid_from_unix":0,"ingested_at_unix":0}')"
retained_entity_id="$(json_field id <<<"$retained_entity_json")"
relation_json="$(request POST /graph/relations "{\"relation_type\":\"supports\",\"from_entity\":\"$linked_entity_id\",\"to_entity\":\"$retained_entity_id\",\"memory_id\":\"$memory_id\",\"attributes\":{\"evidence\":\"semantic-erasure relation attribute\"},\"valid_from_unix\":0,\"ingested_at_unix\":0}")"
relation_id="$(json_field id <<<"$relation_json")"
erase_json="$(request POST /erase "{\"memory_id\":\"$memory_id\",\"authorization_id\":\"case-2026-004\"}")"

python3 -c 'import json,sys
payload = json.loads(sys.argv[1])
assert payload["applied"] is True
assert payload["irreversible"] is True
assert payload["tombstone"]["memory_id"] == sys.argv[2]
assert payload["tombstone"]["scope"] == {"repository": "semantic-erasure", "team": None, "visibility": "repository"}
assert payload["tombstone"]["destroyed_record_key_count"] >= 3
assert len(payload["tombstone"]["authorization_id_hash"]) == 64
assert len(payload["tombstone"]["integrity_hash"]) == 64
assert "authorization_id" not in payload["tombstone"]
assert "case-2026-004" not in json.dumps(payload)' \
  "$erase_json" "$memory_id"

if [[ "$erase_json" == *"$content"* ]]; then
  echo "semantic-erasure response leaked content" >&2
  exit 1
fi
if [[ "$(json_field memory_count <<<"$(request GET /inspect)")" != "0" ]]; then
  echo "semantic-erased memory remained materialized" >&2
  exit 1
fi
if [[ "$(request POST /recall '{"query_vector":[1,0],"top_k":3,"now_unix":0}')" != "[]" ]]; then
  echo "semantic-erased memory remained recallable" >&2
  exit 1
fi
graph_json="$(request GET /graph?as_of_unix=0)"
python3 -c 'import json,sys
graph = json.loads(sys.argv[1])
assert {entity["id"] for entity in graph["entities"]} == {sys.argv[2]}
assert graph["relations"] == []
assert sys.argv[3] not in json.dumps(graph)' \
  "$graph_json" "$retained_entity_id" "$relation_id"
if [[ "$graph_json" == *"semantic-erasure graph payload"* || "$graph_json" == *"semantic-erasure graph attribute"* ]]; then
  echo "semantic-erasure graph response leaked residue" >&2
  exit 1
fi
events_json="$(request GET /events)"
python3 -c 'import json,sys
events = json.loads(sys.argv[1])["events"]
kinds = {event["kind"] for event in events}
assert "memory_semantically_erased" in kinds' "$events_json"
if [[ "$events_json" == *"$content"* ]]; then
  echo "semantic-erasure events leaked content" >&2
  exit 1
fi

stop_server
for payload in \
  "$content" \
  "semantic-erasure graph payload" \
  "semantic-erasure graph attribute" \
  "semantic-erasure relation attribute"; do
  if rg -a -F -q -- "$payload" "$db"; then
    echo "encrypted semantic-erasure store contained plaintext payload" >&2
    exit 1
  fi
done

start_server
if [[ "$(json_field memory_count <<<"$(request GET /inspect)")" != "0" ]]; then
  echo "semantic-erased memory recovered after restart" >&2
  exit 1
fi
stop_server
