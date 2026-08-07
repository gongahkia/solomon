#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${1:?usage: perf-cold-render.sh /path/to/git-repository}"
tmp="$(mktemp -d -t shisa-perf-cold-XXXXXX)"
sock="$tmp/shisa.sock"
log="$tmp/shisad.log"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'perf-cold-render: daemon socket not ready\n' >&2
  exit 1
}

"$root/zig-out/bin/shisa" prompt --socket "$sock" --shell zsh --cwd "$repo" --cols 80 --rows 24 --no-async >/dev/null
