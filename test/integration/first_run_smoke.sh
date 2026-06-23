#!/usr/bin/env bash
# T19: first-run smoke. Starting from a fresh $HOME, the user should be able to
# run `shisa init`, source no hook (we don't need an actual shell), boot shisad,
# and get a real rendered prompt back from `shisa prompt`. This verifies the
# new-user path that no other integration test currently covers.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -x "$root/zig-out/bin/shisa" && -x "$root/zig-out/bin/shisad" ]] || {
  printf 'shisa / shisad not built; run zig build first\n' >&2
  exit 1
}

# macOS Unix sockets cap at ~104 chars. mktemp -d under /var/folders/... blows
# that budget once we append /runtime/shisa/shisad.sock. Use /tmp directly.
tmp="/tmp/shisa-fr-$$"
rm -rf "$tmp"
mkdir -p "$tmp"
home="$tmp/home"
xdg_config="$home/.config"
xdg_runtime="$tmp/runtime"
xdg_cache="$tmp/cache"
sock="$xdg_runtime/shisa/shisad.sock"
log="$tmp/shisad.log"

mkdir -p "$home" "$xdg_config" "$xdg_runtime/shisa" "$xdg_cache"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

export HOME="$home"
export XDG_CONFIG_HOME="$xdg_config"
export XDG_RUNTIME_DIR="$xdg_runtime"
export XDG_CACHE_HOME="$xdg_cache"

# 1. shisa init writes a default shisa.toml
"$root/zig-out/bin/shisa" init >/dev/null
config_path="$xdg_config/shisa/shisa.toml"
[[ -f "$config_path" ]] || {
  printf 'first-run smoke: shisa init did not write %s\n' "$config_path" >&2
  exit 1
}

# 2. daemon boots and listens
"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'first-run smoke: shisad socket not ready\n' >&2
  cat "$log" >&2 || true
  exit 1
}

# 3. shisa prompt returns non-empty output that ends with the prompt terminator
prompt_out=$("$root/zig-out/bin/shisa" prompt --socket "$sock" --shell zsh --cwd "$home")
[[ -n "$prompt_out" ]] || {
  printf 'first-run smoke: empty prompt output\n' >&2
  exit 1
}
case "$prompt_out" in
  *"> "*) ;;
  *)
    printf 'first-run smoke: prompt output missing "> " terminator:\n' >&2
    printf '%s\n' "$prompt_out" | od -c | head -5 >&2
    exit 1
    ;;
esac

# 4. shisa doctor exits 0 against the fresh setup
"$root/zig-out/bin/shisa" doctor --socket "$sock" >/dev/null 2>&1 || {
  printf 'first-run smoke: shisa doctor returned non-zero\n' >&2
  "$root/zig-out/bin/shisa" doctor --socket "$sock" >&2 || true
  exit 1
}

printf 'first-run smoke: ok (config=%s prompt_bytes=%d)\n' "$config_path" "${#prompt_out}"
