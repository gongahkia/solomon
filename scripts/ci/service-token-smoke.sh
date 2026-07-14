#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/service-token.redb"
bind="${SHIBAHAMA_SERVICE_TOKEN_BIND:-127.0.0.1:8880}"
base="http://${bind}"
api_key="service-token-smoke-api-key"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
bootstrap_secret="service-token-bootstrap-secret-000001"
recovery_secret="service-token-recovery-secret-000001"
namespace="service-token-smoke"

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

start_server() {
  SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" \
  SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET="$bootstrap_secret" \
  SHIBAHAMA_ADMIN_RECOVERY_SECRET="$recovery_secret" \
  cargo run -q -p shibahama-cli -- serve \
    --path "$db" \
    --dimensions 2 \
    --api-key "$api_key" \
    --namespace "$namespace" \
    --rbac-enforce \
    --bind "$bind" >"$tmpdir/server.log" 2>&1 &
  server_pid=$!

  for _ in {1..160}; do
    if curl -fsS "$base/healthz" >/dev/null 2>&1; then
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

auth_headers=(
  -H "x-api-key: $api_key"
  -H "x-shibahama-namespace: $namespace"
)

expect_status() {
  local expected="$1"
  shift
  local actual
  actual="$(curl -sS -o /dev/null -w '%{http_code}' "$@")"
  if [[ "$actual" != "$expected" ]]; then
    echo "expected HTTP $expected, got $actual" >&2
    exit 1
  fi
}

issue_token() {
  local expires_at="$1"
  curl -fsS -X POST "${auth_headers[@]}" -H 'content-type: application/json' \
    -d "{\"role\":\"reader\",\"expires_at_unix\":$expires_at}" "$base/tokens"
}

cd "$ROOT"
start_server

bootstrap_json="$(curl -fsS -X POST "${auth_headers[@]}" -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"initialized": True}' "$bootstrap_json"

expires_at="$(python3 -c 'import time; print(int(time.time()) + 3600)')"
issued_json="$(issue_token "$expires_at")"
reader_token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<<"$issued_json")"
reader_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"]["id"])' <<<"$issued_json")"
python3 -c 'import json,sys
value = json.loads(sys.argv[1])
assert value["token"]["role"] == "reader"
assert value["token"]["principal"].startswith("service:")
assert value["access_token"].startswith("shb_at_")' "$issued_json"

token_headers=(
  -H "Authorization: Bearer $reader_token"
  -H "x-shibahama-namespace: $namespace"
)
expect_status 200 "${token_headers[@]}" "$base/readyz"
expect_status 403 "${token_headers[@]}" -H 'x-shibahama-scope-visibility: team' \
  -H 'x-shibahama-scope-team: other-team' "$base/readyz"
expect_status 403 -X POST "${token_headers[@]}" -H 'content-type: application/json' \
  -d '{"content":"reader token must not write","vector":[1.0,0.0],"source_kind":"user"}' "$base/write"

rotated_json="$(curl -fsS -X POST "${auth_headers[@]}" -H 'content-type: application/json' \
  -d "{\"expires_at_unix\":$expires_at}" "$base/tokens/$reader_id/rotate")"
replacement_token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<<"$rotated_json")"
expect_status 401 -H "Authorization: Bearer $reader_token" -H "x-shibahama-namespace: $namespace" "$base/readyz"
expect_status 200 -H "Authorization: Bearer $replacement_token" -H "x-shibahama-namespace: $namespace" "$base/readyz"
replacement_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"]["id"])' <<<"$rotated_json")"
revoke_json="$(curl -fsS -X POST "${auth_headers[@]}" "$base/tokens/$replacement_id/revoke")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"revoked": True}' "$revoke_json"
expect_status 401 -H "Authorization: Bearer $replacement_token" -H "x-shibahama-namespace: $namespace" "$base/readyz"

audit_json="$(curl -fsS "${auth_headers[@]}" "$base/tokens/audit")"
python3 -c 'import json,sys
records = json.loads(sys.argv[1])
assert [record["action"] for record in records] == ["issued", "rotated", "revoked"]
assert all("commitment" not in record and "access_token" not in record for record in records)' "$audit_json"
authorization_audit="$(curl -fsS "${auth_headers[@]}" "$base/rbac/audit")"
python3 -c 'import json,sys
records = json.loads(sys.argv[1])
token_records = [record for record in records if record.get("principal_class") == "service_token"]
agent_records = [record for record in records if record.get("principal_class") == "api_key"]
assert any(record["allowed"] and record["required_role"] == "reader" for record in token_records)
assert any(not record["allowed"] and record["required_role"] == "writer" for record in token_records)
assert all(record.get("actor_class") == "automation" for record in token_records)
assert agent_records and all(record.get("actor_class") == "agent" for record in agent_records)
assert all(not set(record).intersection({"content", "claims", "access_token", "secret", "token"}) for record in records)' "$authorization_audit"

stop_server
for payload in "$reader_token" "$replacement_token"; do
  if rg -a -F -q -- "$payload" "$db" "$tmpdir/server.log"; then
    echo "service token bearer material leaked to durable state or server logs" >&2
    exit 1
  fi
done

start_server
audit_after_restart="$(curl -fsS "${auth_headers[@]}" "$base/tokens/audit")"
python3 -c 'import json,sys
assert len(json.loads(sys.argv[1])) == 3' "$audit_after_restart"
