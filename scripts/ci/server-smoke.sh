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

request_scoped() {
  local visibility="$1"
  local team="$2"
  local method="$3"
  local path="$4"
  local body="${5:-}"
  local scope_headers=(-H "x-shibahama-scope-visibility: ${visibility}")

  if [[ -n "$team" ]]; then
    scope_headers+=(-H "x-shibahama-scope-team: ${team}")
  fi

  if [[ -n "$body" ]]; then
    curl -fsS \
      -X "$method" \
      -H "content-type: application/json" \
      -H "x-api-key: ${api_key}" \
      -H "x-shibahama-namespace: ${namespace}" \
      "${scope_headers[@]}" \
      --data "$body" \
      "${base}${path}"
  else
    curl -fsS \
      -X "$method" \
      -H "x-api-key: ${api_key}" \
      -H "x-shibahama-namespace: ${namespace}" \
      "${scope_headers[@]}" \
      "${base}${path}"
  fi
}

request() {
  request_scoped repository "" "$@"
}

request_team() {
  request_scoped team team-smoke "$@"
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value = value[int(part)] if part.isdigit() else value[part]
print(value)' "$field"
}

capabilities_json="$(curl -fsS "${base}/capabilities")"
if [[ "$(json_field schema_version <<<"$capabilities_json")" != "1" ]]; then
  echo "unexpected capability schema version" >&2
  exit 1
fi

item_json="$(request_team POST /write '{"content":"Server smoke memory","vector":[1,0],"source_kind":"user","source_ref":"server-smoke","valid_from_unix":0,"ingested_at_unix":0,"scope":{"repository":"smoke","team":"team-smoke","visibility":"team"}}')"
memory_id="$(json_field id <<<"$item_json")"
if [[ "$(json_field scope.repository <<<"$item_json")" != "$namespace" || "$(json_field scope.team <<<"$item_json")" != "team-smoke" || "$(json_field scope.visibility <<<"$item_json")" != "team" ]]; then
  echo "scope serialization mismatch" >&2
  exit 1
fi

invalid_write_status="$(curl -sS -o "$tmpdir/invalid-write.json" -w '%{http_code}' \
  -X POST \
  -H 'content-type: application/json' \
  -H "x-api-key: ${api_key}" \
  -H "x-shibahama-namespace: ${namespace}" \
  -H 'x-shibahama-scope-visibility: repository' \
  --data '{"content":"invalid vector","vector":[0]}' \
  "${base}/write")"
if [[ "$invalid_write_status" != "400" ]]; then
  echo "invalid write returned HTTP $invalid_write_status" >&2
  exit 1
fi
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload == {
    "error": "vector index operation failed",
    "code": "SHIBA_VECTOR",
    "severity": "fatal",
    "retryable": False,
    "detail": "vector index operation failed",
}' "$tmpdir/invalid-write.json"

invalidated_json="$(request POST /write '{"content":"Invalidated server smoke memory","vector":[0,1],"source_kind":"file","source_ref":"server-smoke-invalidated","valid_from_unix":0,"ingested_at_unix":0}')"
invalidated_id="$(json_field id <<<"$invalidated_json")"
request POST /invalidate "{\"memory_id\":\"${invalidated_id}\",\"valid_to_unix\":10}" >/dev/null

team_inspect="$(request_team GET /inspect)"
repository_inspect="$(request GET /inspect)"
python3 -c 'import json,sys
team_id, repository_id, team, repository = sys.argv[1:]
team_ids = {item["id"] for item in json.loads(team)["memories"]}
repository_ids = {item["id"] for item in json.loads(repository)["memories"]}
assert team_id in team_ids and repository_id not in team_ids
assert repository_id in repository_ids and team_id not in repository_ids' \
  "$memory_id" "$invalidated_id" "$team_inspect" "$repository_inspect"

timeline_json="$(request_team POST /timeline '{"query_vector":[1,0],"top_k":1,"as_of_unix":0}')"
if [[ "$(json_field 0.id <<<"$timeline_json")" != "$memory_id" ]]; then
  echo "team timeline crossed scope" >&2
  exit 1
fi
degraded_json="$(request_team POST /recall/degraded '{"query_vector":[1,0],"top_k":1,"now_unix":0}')"
if [[ "$(json_field candidates.0.id <<<"$degraded_json")" != "$memory_id" || "$(json_field unavailable_stages <<<"$degraded_json")" != "[]" ]]; then
  echo "degraded recall contract mismatch" >&2
  exit 1
fi
request_team POST /reinforce "{\"memory_id\":\"${memory_id}\",\"outcome\":\"cited\"}" >/dev/null
request_team POST /challenge "{\"memory_id\":\"${memory_id}\",\"reason\":\"server smoke challenge\"}" >/dev/null
request_team POST /affirm "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request_team POST /pin "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request_team POST /unpin "{\"memory_id\":\"${memory_id}\"}" >/dev/null
request_team POST /correct "{\"memory_id\":\"${memory_id}\",\"proposed_content\":\"Server smoke corrected memory\"}" >/dev/null
request POST /consolidate '{"now_unix":86400,"allow_store_wide":true}' >/dev/null
team_events="$(request_team GET /events)"
repository_events="$(request GET /events)"
python3 -c 'import json,sys
team_id, repository_id, team, repository = sys.argv[1:]
team_payload = json.loads(team)
repository_payload = json.loads(repository)
assert all(repository_id not in event["memory_ids"] for event in team_payload["events"])
assert all(team_id not in event["memory_ids"] for event in repository_payload["events"])' \
  "$memory_id" "$invalidated_id" "$team_events" "$repository_events"
request_team GET "/audit/${memory_id}" >/dev/null
tideline_json="$(request_team GET /tideline/snapshot)"
if [[ "$(json_field memory_count <<<"$tideline_json")" == "0" ]]; then
  echo "team Tideline projection is empty" >&2
  exit 1
fi

project_json="$(request POST /graph/entities '{"entity_type":"Project","label":"Server Smoke Project","stable_key":"project:server-smoke","attributes":{"scope":"server-smoke"},"valid_from_unix":0,"ingested_at_unix":0}')"
project_id="$(json_field id <<<"$project_json")"
claim_json="$(request POST /graph/entities '{"entity_type":"Claim","label":"Server Smoke Claim","stable_key":"claim:server-smoke","attributes":{"scope":"server-smoke"},"valid_from_unix":0,"ingested_at_unix":0}')"
claim_id="$(json_field id <<<"$claim_json")"
relation_json="$(request POST /graph/relations "{\"relation_type\":\"supports\",\"from_entity\":\"${project_id}\",\"to_entity\":\"${claim_id}\",\"memory_id\":\"${invalidated_id}\",\"attributes\":{\"scope\":\"server-smoke\"},\"valid_from_unix\":0,\"ingested_at_unix\":0}")"
relation_id="$(json_field id <<<"$relation_json")"

request GET "/graph/entities/${project_id}" >/dev/null
request GET "/graph/relations/${relation_id}" >/dev/null
request GET /graph?as_of_unix=0 >/dev/null
request POST /graph/traverse "{\"start_entity\":\"${project_id}\",\"max_hops\":1,\"as_of_unix\":0}" >/dev/null
request DELETE "/graph/relations/${relation_id}?valid_to_unix=10" >/dev/null
request DELETE "/graph/entities/${claim_id}?valid_to_unix=10" >/dev/null

echo "server smoke passed"
