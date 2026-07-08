#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-snapshot-$$.sock"
log="/tmp/shisa-snapshot-$$.log"
xdg="/tmp/shisa-snapshot-$$-config"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock" "$log"
  rm -rf "$xdg"
}
trap cleanup EXIT

mkdir -p "$xdg/shisa"
cat >"$xdg/shisa/shisa.toml" <<'TOML'
version = 1
theme = "plain"
locale = "auto"

[prompt]
modules = ["cwd", "exit_status", "jobs", "cmd_duration"]
right_modules = []
TOML

"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!

for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done

[[ -S "$sock" ]] || {
  printf 'snapshot daemon socket not ready\n' >&2
  exit 1
}

actual="$(env HOSTNAME=localhost SSH_CONNECTION= XDG_CONFIG_HOME="$xdg" "$root/zig-out/bin/shisa" prompt --socket "$sock" --cwd /tmp/shisa-snapshot --exit 7 --jobs 2 --duration-ms 1500 --shell zsh --cols 80 --rows 24)"
expected=$'\e]7;file://localhost/tmp/shisa-snapshot\a/tmp/shisa-snapshot \e[31mexit:7\e[0m jobs:2 took:1.5s> '

if [[ "$actual" != "$expected" ]]; then
  printf 'snapshot mismatch\nexpected: %q\nactual:   %q\n' "$expected" "$actual" >&2
  exit 1
fi
