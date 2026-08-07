#!/usr/bin/env bash
# The context API is intentionally a single local, framed request. This proves
# that the CLI and daemon agree on the read-only snapshot protocol.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
shisa="$root/zig-out/bin/shisa"
shisad="$root/zig-out/bin/shisad"
[[ -x "$shisa" && -x "$shisad" ]] || {
  printf 'context API: shisa / shisad not built; run zig build debug\n' >&2
  exit 1
}

tmp="/tmp/shisa-context-api-$$"
socket_path="$tmp/shisa.sock"
mkdir -p "$tmp/repo"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

"$shisad" --foreground --socket "$socket_path" --log "$tmp/shisad.log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$socket_path" ]] && break
  sleep 0.01
done
[[ -S "$socket_path" ]] || {
  printf 'context API: daemon socket not ready\n' >&2
  exit 1
}

output="$("$shisa" context --json --socket "$socket_path" --cwd "$tmp/repo")"
grep -Fq "\"v\":1" <<<"$output"
grep -Fq '"schema":"shisa.context/v1"' <<<"$output"
grep -Fq "\"cwd\":\"$tmp/repo\"" <<<"$output"
grep -Fq '"git":{"state":"unknown"' <<<"$output"
grep -Fq '"cloud":{' <<<"$output"
printf 'context API: ok (local read-only snapshot)\n'
