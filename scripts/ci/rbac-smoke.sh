#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/rbac.redb"
bind="${SHIBAHAMA_RBAC_BIND:-127.0.0.1:8879}"
base="http://${bind}"
api_key="rbac-smoke-api-key"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
bootstrap_secret="rbac-bootstrap-secret-for-smoke-test-0001"
recovery_secret="rbac-recovery-secret-for-smoke-test-00001"
namespace="rbac-smoke"

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

  for _ in {1..40}; do
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

cd "$ROOT"
start_server

expect_status 403 "${auth_headers[@]}" "$base/readyz"
expect_status 403 -X POST "${auth_headers[@]}" -H 'content-type: application/json' \
  -d '{"principal":"oidc:reader","role":"reader"}' "$base/rbac/grants"

bootstrap_json="$(curl -fsS -X POST "${auth_headers[@]}" -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"initialized": True}' "$bootstrap_json"
expect_status 200 "${auth_headers[@]}" "$base/readyz"

grant_json="$(curl -fsS -X POST "${auth_headers[@]}" -H 'content-type: application/json' \
  -d '{"principal":"oidc:reader","role":"reader"}' "$base/rbac/grants")"
python3 -c 'import json,sys
grant = json.loads(sys.argv[1])
assert grant["principal"] == "oidc:reader"
assert grant["role"] == "reader"
assert grant["scope"] == {"repository": "rbac-smoke", "team": None, "visibility": "repository"}' "$grant_json"

grants_json="$(curl -fsS "${auth_headers[@]}" "$base/rbac/grants")"
python3 -c 'import json,sys
grants = json.loads(sys.argv[1])
assert len(grants) == 1 and grants[0]["role"] == "reader"' "$grants_json"

revoke_json="$(curl -fsS -X POST "${auth_headers[@]}" -H 'content-type: application/json' \
  -d '{"principal":"oidc:reader"}' "$base/rbac/revoke")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"applied": True}' "$revoke_json"

audit_json="$(curl -fsS "${auth_headers[@]}" "$base/rbac/audit")"
python3 -c 'import json,sys
records = json.loads(sys.argv[1])
assert any(record["audit_action"] == "role_granted" and record["subject"] == "oidc:reader" for record in records)
assert any(record["audit_action"] == "role_revoked" and record["subject"] == "oidc:reader" for record in records)
assert any(record["audit_action"] == "decision" and not record["allowed"] and record["required_role"] == "reader" for record in records)
assert any(record["audit_action"] == "decision" and record["allowed"] and record["required_role"] == "reader" for record in records)' "$audit_json"

stop_server
start_server
grants_after_restart="$(curl -fsS "${auth_headers[@]}" "$base/rbac/grants")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == []' "$grants_after_restart"
audit_after_restart="$(curl -fsS "${auth_headers[@]}" "$base/rbac/audit")"
python3 -c 'import json,sys
assert len(json.loads(sys.argv[1])) >= 4' "$audit_after_restart"
