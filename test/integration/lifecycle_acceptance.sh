#!/usr/bin/env bash
# RFC-0008 acceptance coverage that can run without a remote host, container,
# or privileged sudo session. It tests the observable local contracts: stale
# socket replacement, crash recovery under the supervisor, and a tmux-shaped
# session surviving that restart. The separate nix-shell integration covers the
# environment-hash cache-key path when Nix is installed.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
shisa="$root/zig-out/bin/shisa"
shisad="$root/zig-out/bin/shisad"
[[ -x "$shisa" && -x "$shisad" ]] || {
  printf 'lifecycle acceptance: shisa / shisad not built; run zig build debug\n' >&2
  exit 1
}

tmp="/tmp/shisa-lifecycle-$$"
stale_sock="$tmp/stale.sock"
supervised_sock="$tmp/supervised.sock"
mkdir -p "$tmp/repo"
git -C "$tmp/repo" init -q -b main
git -C "$tmp/repo" config user.email lifecycle@shisa.local
git -C "$tmp/repo" config user.name lifecycle
printf 'fixture\n' >"$tmp/repo/file"
git -C "$tmp/repo" add file
git -C "$tmp/repo" commit -qm fixture

cleanup() {
  if [[ -n "${stale_pid:-}" ]]; then
    kill "$stale_pid" >/dev/null 2>&1 || true
    wait "$stale_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "${supervisor_pid:-}" ]]; then
    current_child="$(pgrep -P "$supervisor_pid" 2>/dev/null | head -n 1 || true)"
    kill "$supervisor_pid" >/dev/null 2>&1 || true
    wait "$supervisor_pid" >/dev/null 2>&1 || true
    if [[ -n "$current_child" ]]; then
      kill "$current_child" >/dev/null 2>&1 || true
      wait "$current_child" >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

wait_for_socket() {
  local socket_path="$1"
  for _ in {1..200}; do
    [[ -S "$socket_path" ]] && return 0
    sleep 0.01
  done
  return 1
}

render() {
  "$shisa" prompt --socket "$1" --cwd "$tmp/repo" --shell zsh --cols 80 --rows 24 --no-async
}

wait_for_render() {
  local socket_path="$1"
  for _ in {1..200}; do
    if render "$socket_path" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.01
  done
  return 1
}

# A bind/close leaves a real Unix socket node without a listener, matching the
# post-crash condition that the daemon must repair before it can listen.
python3 - "$stale_sock" <<'PY'
import socket
import sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sys.argv[1])
s.close()
PY
[[ -S "$stale_sock" ]]
"$shisad" --foreground --socket "$stale_sock" --log "$tmp/stale.log" >/dev/null 2>&1 &
stale_pid=$!
wait_for_socket "$stale_sock" || {
  printf 'lifecycle acceptance: stale socket was not replaced\n' >&2
  exit 1
}
wait_for_render "$stale_sock" || {
  printf 'lifecycle acceptance: stale socket did not accept renders\n' >&2
  exit 1
}
kill "$stale_pid"
wait "$stale_pid" || true
unset stale_pid

# The supervisor must bring up a replacement after an unclean daemon exit.
"$shisa" supervisor --daemon "$shisad" --socket "$supervised_sock" \
  --backoff-ms 10 --max-backoff-ms 25 --heartbeat-ms 25 --max-restarts 2 --no-self-disable \
  >"$tmp/supervisor.log" 2>&1 &
supervisor_pid=$!
wait_for_socket "$supervised_sock" || {
  printf 'lifecycle acceptance: supervised socket not ready\n' >&2
  exit 1
}
first_child="$(pgrep -P "$supervisor_pid" | head -n 1)"
[[ -n "$first_child" ]]
# SIGTERM is a graceful daemon shutdown and the supervisor intentionally treats
# it as clean. SIGKILL models the unclean crash/EOF case from RFC-0008.
kill -9 "$first_child"

replacement_child=""
for _ in {1..200}; do
  candidate="$(pgrep -P "$supervisor_pid" 2>/dev/null | head -n 1 || true)"
  if [[ -n "$candidate" && "$candidate" != "$first_child" ]] && wait_for_render "$supervised_sock"; then
    replacement_child="$candidate"
    break
  fi
  sleep 0.01
done
[[ -n "$replacement_child" ]] || {
  printf 'lifecycle acceptance: supervisor did not replace daemon after crash\n' >&2
  cat "$tmp/supervisor.log" >&2 || true
  exit 1
}

# tmux is transparent to the daemon connection model; a resume after restart
# must render through the replacement without retaining a stale connection.
tmux_prompt="$(TMUX="$tmp/tmux,1,0" TMUX_PANE='%42' render "$supervised_sock")"
[[ -n "$tmux_prompt" ]] || {
  printf 'lifecycle acceptance: tmux-shaped session did not render after restart\n' >&2
  exit 1
}

printf 'lifecycle acceptance: ok (stale socket, supervisor crash recovery, tmux resume)\n'
