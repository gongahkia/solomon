#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
server_pid=""
db="$tmpdir/rate-limit.redb"
bind="${SHIBAHAMA_RATE_LIMIT_BIND:-127.0.0.1:8883}"
base="http://${bind}"
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
  --rate-limit-requests-per-window 2 \
  --rate-limit-window-seconds 60 \
  --rate-limit-burst 2 >"$tmpdir/server.log" 2>&1 &
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

for _ in 1 2; do
  status="$(curl -sS -o /dev/null -w '%{http_code}' "$base/readyz")"
  if [[ "$status" != "200" ]]; then
    echo "burst request unexpectedly returned HTTP $status" >&2
    exit 1
  fi
done

headers="$tmpdir/limited.headers"
body="$tmpdir/limited.json"
status="$(curl -sS -D "$headers" -o "$body" -w '%{http_code}' "$base/readyz")"
if [[ "$status" != "429" ]]; then
  echo "exhausted request returned HTTP $status" >&2
  exit 1
fi
python3 - "$headers" "$body" <<'PY'
import json,sys
headers = open(sys.argv[1], encoding="iso-8859-1").read().lower()
body = json.load(open(sys.argv[2], encoding="utf-8"))
assert "retry-after: 30" in headers
assert body == {
    "error": "request rate limited",
    "code": "SHIBA_RATE_LIMITED",
    "severity": "recoverable",
    "retryable": True,
    "retry_after_seconds": 30,
    "detail": "request rate limited",
}
assert "remaining" not in json.dumps(body)
PY

scope_status="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'x-shibahama-scope-visibility: team' \
  -H 'x-shibahama-scope-team: different-scope' \
  "$base/readyz")"
if [[ "$scope_status" != "200" ]]; then
  echo "different scope was unfairly rate-limited with HTTP $scope_status" >&2
  exit 1
fi
