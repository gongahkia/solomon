#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/admin-bootstrap.redb"
bind="${SHIBAHAMA_ADMIN_BOOTSTRAP_BIND:-127.0.0.1:8878}"
base="http://${bind}"
api_key="admin-bootstrap-smoke"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
bootstrap_secret="bootstrap-secret-for-smoke-test-0001"
recovery_secret="recovery-secret-for-smoke-test-00001"
namespace="admin-bootstrap"

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
    --bind "$bind" >"$tmpdir/server.log" 2>&1 &
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

expect_status 401 -X POST -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap"
expect_status 401 -X POST "${auth_headers[@]}" "$base/admin/bootstrap"

bootstrap_json="$(curl -fsS -X POST "${auth_headers[@]}" -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"initialized": True}' "$bootstrap_json"
expect_status 403 -X POST "${auth_headers[@]}" -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap"
expect_status 401 -X POST -H "x-shibahama-recovery-secret: $recovery_secret" "$base/admin/recover"
expect_status 401 -X POST "${auth_headers[@]}" -H 'x-shibahama-recovery-secret: wrong-recovery-secret-value-000000' "$base/admin/recover"

recovery_json="$(curl -fsS -X POST "${auth_headers[@]}" -H "x-shibahama-recovery-secret: $recovery_secret" "$base/admin/recover")"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"recovered": True}' "$recovery_json"

audit_json="$(curl -fsS "${auth_headers[@]}" "$base/admin/audit")"
python3 -c 'import json,sys
records = json.loads(sys.argv[1])
assert [record["action"] for record in records] == [
    "bootstrap_window_opened",
    "administrator_bootstrapped",
    "administrator_recovered",
]
assert all("secret" not in record for record in records)' "$audit_json"
if [[ "$audit_json" == *"$bootstrap_secret"* || "$audit_json" == *"$recovery_secret"* ]]; then
  echo "administration audit leaked a raw operator secret" >&2
  exit 1
fi

stop_server
for payload in "$bootstrap_secret" "$recovery_secret"; do
  if rg -a -F -q -- "$payload" "$db" "$tmpdir/server.log"; then
    echo "administration bootstrap leaked a raw operator secret" >&2
    exit 1
  fi
done

start_server
expect_status 403 -X POST "${auth_headers[@]}" -H "x-shibahama-bootstrap-secret: $bootstrap_secret" "$base/admin/bootstrap"
audit_after_restart="$(curl -fsS "${auth_headers[@]}" "$base/admin/audit")"
if [[ "$audit_after_restart" != "$audit_json" ]]; then
  echo "administration audit changed after restart" >&2
  exit 1
fi
