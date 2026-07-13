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

capture_simulation="$(request POST /policy/simulate/capture '{"source_kind":"agent","actor":"automation","intent":"automatic"}')"
recall_simulation="$(request POST /policy/simulate/recall '{"top_k":20,"max_context_tokens":5000,"include_cold":true,"include_instructions":true}')"
python3 -c 'import json,sys
capture, recall = map(json.loads, sys.argv[1:])
assert capture["decision"]["outcome"] == "deny"
assert recall["decision"]["effective_candidates"] == 8
assert recall["decision"]["effective_context_tokens"] == 2048' \
  "$capture_simulation" "$recall_simulation"
if [[ "$(json_field memory_count <<<"$(request GET /inspect)")" != "0" ]]; then
  echo "policy simulation mutated memory state" >&2
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

mcp_init_headers="$tmpdir/mcp-init.headers"
mcp_init_body="$tmpdir/mcp-init.json"
curl -fsS -D "$mcp_init_headers" -o "$mcp_init_body" \
  -X POST \
  -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  -H "x-api-key: ${api_key}" \
  -H "x-shibahama-namespace: ${namespace}" \
  -H 'x-shibahama-scope-visibility: repository' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
  "${base}/mcp"
mcp_session="$(awk 'tolower($1)=="mcp-session-id:" {gsub("\r", "", $2); print $2}' "$mcp_init_headers")"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["protocolVersion"] == "2025-11-25"
assert payload["result"]["capabilities"]["resources"] == {}
assert payload["result"]["capabilities"]["experimental"]["shibahama"]["actorClass"] == "service"' "$mcp_init_body"
if [[ -z "$mcp_session" ]]; then
  echo "MCP initialization did not return a session" >&2
  exit 1
fi
mcp_headers=(
  -H 'accept: application/json, text/event-stream'
  -H 'content-type: application/json'
  -H "x-api-key: ${api_key}"
  -H "x-shibahama-namespace: ${namespace}"
  -H 'x-shibahama-scope-visibility: repository'
  -H "mcp-session-id: ${mcp_session}"
  -H 'mcp-protocol-version: 2025-11-25'
)
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' -H "x-shibahama-namespace: ${namespace}" -H 'x-shibahama-scope-visibility: repository' --data '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' "${base}/mcp")" != "401" ]]; then
  echo "MCP missing authentication was accepted" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","method":"notifications/initialized"}' "${base}/mcp")" != "202" ]]; then
  echo "MCP initialized notification was not accepted" >&2
  exit 1
fi
mcp_tools="$tmpdir/mcp-tools.json"
curl -fsS -o "$mcp_tools" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' "${base}/mcp"
python3 -c 'import json,sys
tools = json.load(open(sys.argv[1], encoding="utf-8"))["result"]["tools"]
assert len(tools) == 7
assert all(tool["inputSchema"]["x-shibahama-schema-version"] == 1 for tool in tools)' "$mcp_tools"
mcp_resources="$tmpdir/mcp-resources.json"
curl -fsS -o "$mcp_resources" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":3,"method":"resources/list"}' "${base}/mcp"
python3 -c 'import json,sys
resources = json.load(open(sys.argv[1], encoding="utf-8"))["result"]["resources"]
assert len(resources) == 5
assert all(resource["uri"].startswith("shibahama://v1/") for resource in resources)' "$mcp_resources"
mcp_scope_resource="$tmpdir/mcp-scope-resource.json"
curl -fsS -o "$mcp_scope_resource" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"shibahama://v1/scope"}}' "${base}/mcp"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
resource = json.loads(payload["result"]["contents"][0]["text"])
assert resource["schemaVersion"] == 1
assert resource["scope"]["repository"] == "smoke"
assert resource["principal"] == "api_key"
assert resource["actorClass"] == "service"' "$mcp_scope_resource"
mcp_spoofed_actor="$tmpdir/mcp-spoofed-actor.json"
curl -fsS -o "$mcp_spoofed_actor" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"shibahama_memory_write_v1","arguments":{"schemaVersion":1,"scope":{"repository":"smoke","team":null,"visibility":"repository"},"actor":"human","actorId":"api_key","content":"actor class must not be forgeable","vector":[1,0],"sourceKind":"user","validFromUnix":0,"ingestedAtUnix":0}}}' "${base}/mcp"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["isError"] is True
assert payload["result"]["structuredContent"]["error"]["code"] == "SHIBA_UNAUTHORIZED"
assert "actor class must not be forgeable" not in json.dumps(payload)' "$mcp_spoofed_actor"
mcp_write="$tmpdir/mcp-write.json"
curl -fsS -o "$mcp_write" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"shibahama_memory_write_v1","arguments":{"schemaVersion":1,"scope":{"repository":"smoke","team":null,"visibility":"repository"},"actor":"service","actorId":"api_key","content":"MCP server smoke memory","vector":[1,0],"sourceKind":"user","validFromUnix":0,"ingestedAtUnix":0}}}' "${base}/mcp"
mcp_memory_id="$(python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["isError"] is False
assert payload["result"]["structuredContent"]["result"]["policyOutcome"] == "allowed"
print(payload["result"]["structuredContent"]["result"]["memory"]["id"])' "$mcp_write")"
mcp_recall="$tmpdir/mcp-recall.json"
curl -fsS -o "$mcp_recall" -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"shibahama_memory_recall_v1","arguments":{"schemaVersion":1,"scope":{"repository":"smoke","team":null,"visibility":"repository"},"queryVector":[1,0],"topK":1,"nowUnix":0}}}' "${base}/mcp"
python3 -c 'import json,sys
memory_id, payload = sys.argv[1:]
payload = json.load(open(payload, encoding="utf-8"))
assert payload["result"]["isError"] is False
assert payload["result"]["structuredContent"]["result"]["candidates"][0]["id"] == memory_id' "$mcp_memory_id" "$mcp_recall"
mcp_missing_confirmation="$tmpdir/mcp-missing-confirmation.json"
curl -fsS -o "$mcp_missing_confirmation" -X POST "${mcp_headers[@]}" --data "{\"jsonrpc\":\"2.0\",\"id\":8,\"method\":\"tools/call\",\"params\":{\"name\":\"shibahama_memory_erase_v1\",\"arguments\":{\"schemaVersion\":1,\"scope\":{\"repository\":\"smoke\",\"team\":null,\"visibility\":\"repository\"},\"actor\":\"service\",\"actorId\":\"api_key\",\"memoryId\":\"${mcp_memory_id}\",\"validToUnix\":2}}}" "${base}/mcp"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["isError"] is True
assert payload["result"]["structuredContent"]["error"]["code"] == "SHIBA_CONFIRMATION_REQUIRED"' "$mcp_missing_confirmation"
mcp_erase="$tmpdir/mcp-erase.json"
curl -fsS -o "$mcp_erase" -X POST "${mcp_headers[@]}" --data "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"shibahama_memory_erase_v1\",\"arguments\":{\"schemaVersion\":1,\"scope\":{\"repository\":\"smoke\",\"team\":null,\"visibility\":\"repository\"},\"actor\":\"service\",\"actorId\":\"api_key\",\"memoryId\":\"${mcp_memory_id}\",\"validToUnix\":2,\"confirmation\":{\"schemaVersion\":1,\"intent\":\"erasure\",\"token\":\"server-erase-confirm-0001\",\"actorId\":\"api_key\",\"scope\":{\"repository\":\"smoke\",\"team\":null,\"visibility\":\"repository\"},\"targetId\":\"${mcp_memory_id}\",\"validToUnix\":2}}}}" "${base}/mcp"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["isError"] is False
assert payload["result"]["structuredContent"]["result"]["applied"] is True' "$mcp_erase"
mcp_erase_retry="$tmpdir/mcp-erase-retry.json"
curl -fsS -o "$mcp_erase_retry" -X POST "${mcp_headers[@]}" --data "{\"jsonrpc\":\"2.0\",\"id\":10,\"method\":\"tools/call\",\"params\":{\"name\":\"shibahama_memory_erase_v1\",\"arguments\":{\"schemaVersion\":1,\"scope\":{\"repository\":\"smoke\",\"team\":null,\"visibility\":\"repository\"},\"actor\":\"service\",\"actorId\":\"api_key\",\"memoryId\":\"${mcp_memory_id}\",\"validToUnix\":2,\"confirmation\":{\"schemaVersion\":1,\"intent\":\"erasure\",\"token\":\"server-erase-confirm-0001\",\"actorId\":\"api_key\",\"scope\":{\"repository\":\"smoke\",\"team\":null,\"visibility\":\"repository\"},\"targetId\":\"${mcp_memory_id}\",\"validToUnix\":2}}}}" "${base}/mcp"
python3 -c 'import json,sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["result"]["isError"] is True
assert payload["result"]["structuredContent"]["error"]["code"] == "SHIBA_CONFIRMATION_CONSUMED"' "$mcp_erase_retry"
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' -H "x-api-key: ${api_key}" -H "x-shibahama-namespace: ${namespace}" -H 'x-shibahama-scope-visibility: team' -H 'x-shibahama-scope-team: team-smoke' -H "mcp-session-id: ${mcp_session}" -H 'mcp-protocol-version: 2025-11-25' --data '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' "${base}/mcp")" != "403" ]]; then
  echo "MCP session accepted a changed scope" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' -H "x-api-key: ${api_key}" -H "x-shibahama-namespace: ${namespace}" -H 'x-shibahama-scope-visibility: repository' -H "mcp-session-id: ${mcp_session}" -H 'mcp-protocol-version: unsupported' --data '{"jsonrpc":"2.0","id":4,"method":"tools/list"}' "${base}/mcp")" != "400" ]]; then
  echo "MCP unsupported protocol version was accepted" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${mcp_headers[@]}" --data '{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":2}}' "${base}/mcp")" != "202" ]]; then
  echo "MCP cancellation notification was not accepted" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'origin: https://attacker.invalid' -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":3,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' "${base}/mcp")" != "403" ]]; then
  echo "MCP origin validation failed" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X GET -H 'accept: text/event-stream' -H "x-api-key: ${api_key}" -H "x-shibahama-namespace: ${namespace}" -H 'x-shibahama-scope-visibility: repository' "${base}/mcp")" != "405" ]]; then
  echo "MCP GET fallback did not return 405" >&2
  exit 1
fi
if [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE -H "x-api-key: ${api_key}" -H "x-shibahama-namespace: ${namespace}" -H 'x-shibahama-scope-visibility: repository' -H "mcp-session-id: ${mcp_session}" -H 'mcp-protocol-version: 2025-11-25' "${base}/mcp")" != "204" ]]; then
  echo "MCP session deletion failed" >&2
  exit 1
fi

echo "server smoke passed"
