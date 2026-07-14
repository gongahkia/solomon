#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/cors.redb"
bind="${SHIBAHAMA_CORS_BIND:-127.0.0.1:8881}"
base="http://${bind}"
origin="https://console.example.test"
encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

cd "$ROOT"
SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" \
cargo run -q -p shibahama-cli -- serve \
  --path "$db" \
  --dimensions 2 \
  --bind "$bind" \
  --cors-origin "$origin" \
  --cors-method GET,POST,DELETE \
  --cors-header authorization,content-type,x-api-key,x-shibahama-namespace \
  --cors-allow-credentials >"$tmpdir/server.log" 2>&1 &
server_pid=$!

for _ in {1..160}; do
  if curl -fsS "$base/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS "$base/healthz" >/dev/null 2>&1; then
  cat "$tmpdir/server.log" >&2 || true
  exit 1
fi

allowed_headers="$tmpdir/allowed.headers"
curl -sS -D "$allowed_headers" -o /dev/null -X OPTIONS \
  -H "Origin: $origin" \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type,x-api-key' \
  "$base/write"
python3 - "$allowed_headers" "$origin" <<'PY'
import sys
headers = open(sys.argv[1], encoding="iso-8859-1").read().lower()
origin = sys.argv[2].lower()
assert f"access-control-allow-origin: {origin}" in headers
assert "access-control-allow-credentials: true" in headers
assert "access-control-allow-methods:" in headers and "post" in headers
assert "access-control-allow-headers:" in headers
for name in ("authorization", "content-type", "x-api-key"):
    assert name in headers
PY

rejected_headers="$tmpdir/rejected.headers"
curl -sS -D "$rejected_headers" -o /dev/null -X OPTIONS \
  -H 'Origin: https://evil.example.test' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type,x-api-key' \
  "$base/write"
if rg -i -q '^access-control-allow-origin:' "$rejected_headers"; then
  echo "rejected origin received an allow-origin response" >&2
  exit 1
fi

method_headers="$tmpdir/method.headers"
curl -sS -D "$method_headers" -o /dev/null -X OPTIONS \
  -H "Origin: $origin" \
  -H 'Access-Control-Request-Method: PUT' \
  -H 'Access-Control-Request-Headers: authorization' \
  "$base/write"
if rg -i '^access-control-allow-methods:.*put' "$method_headers"; then
  echo "unconfigured method received CORS permission" >&2
  exit 1
fi

header_headers="$tmpdir/header.headers"
curl -sS -D "$header_headers" -o /dev/null -X OPTIONS \
  -H "Origin: $origin" \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: x-unconfigured-header' \
  "$base/write"
if rg -i '^access-control-allow-headers:.*x-unconfigured-header' "$header_headers"; then
  echo "unconfigured header received CORS permission" >&2
  exit 1
fi

kill "$server_pid" 2>/dev/null || true
wait "$server_pid" 2>/dev/null || true
server_pid=""
local_bind="${SHIBAHAMA_CORS_LOCAL_BIND:-127.0.0.1:8882}"
local_base="http://${local_bind}"
SHIBAHAMA_ENCRYPTION_KEY="$encryption_key" \
cargo run -q -p shibahama-cli -- serve \
  --path "$tmpdir/cors-local.redb" \
  --dimensions 2 \
  --bind "$local_bind" >"$tmpdir/local.log" 2>&1 &
server_pid=$!
for _ in {1..160}; do
  if curl -fsS "$local_base/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS "$local_base/healthz" >/dev/null 2>&1; then
  cat "$tmpdir/local.log" >&2 || true
  exit 1
fi
local_headers="$tmpdir/local.headers"
curl -sS -D "$local_headers" -o /dev/null -X OPTIONS \
  -H 'Origin: http://localhost:5173' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: x-api-key' \
  "$local_base/readyz"
if ! rg -i -q '^access-control-allow-origin: http://localhost:5173' "$local_headers"; then
  echo "localhost developer default did not receive CORS permission" >&2
  exit 1
fi
if ! rg -F -q 'WARNING: unsafe local CORS defaults are active' "$tmpdir/local.log"; then
  echo "localhost CORS default was not visibly marked unsafe" >&2
  exit 1
fi
