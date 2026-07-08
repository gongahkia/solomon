#!/usr/bin/env bash
set -euo pipefail

root=/src
scenario="${SHISA_E2E_SCENARIO:-hardening}"
require_hardening="${SHISA_E2E_REQUIRE_HARDENING:-0}"
tmp="$(mktemp -d /tmp/shisa-e2e.XXXXXX)"
repo="$tmp/repo"
home="$tmp/home"
xdg_config="$tmp/config"
xdg_cache="$tmp/cache"
xdg_runtime="$tmp/runtime"
sock="$xdg_runtime/shisa.sock"
log="$tmp/shisad.log"
zig_cache="$tmp/zig-cache"
zig_global_cache="$tmp/zig-global-cache"

skip_or_fail() {
  local message="$1"
  if [[ "$require_hardening" == "1" ]]; then
    printf 'hardening-e2e: %s\n' "$message" >&2
    exit 1
  fi
  printf 'hardening-e2e: skip: %s\n' "$message"
  exit 0
}

need_tool() {
  command -v "$1" >/dev/null 2>&1 || skip_or_fail "$scenario requires $1"
}

cleanup() {
  if [[ -n "${sway_pid:-}" ]]; then
    kill "$sway_pid" >/dev/null 2>&1 || true
    wait "$sway_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

case "$scenario" in
  systemd-nspawn)
    need_tool systemd-nspawn
    systemd-nspawn --version >/dev/null
    ;;
  rootless-podman)
    need_tool podman
    podman --version >/dev/null
    if [[ "$(id -u)" == "0" ]]; then
      useradd -m -u 1000 shisae2e >/dev/null 2>&1 || true
      grep -q '^shisae2e:' /etc/subuid 2>/dev/null || printf 'shisae2e:100000:65536\n' >>/etc/subuid
      grep -q '^shisae2e:' /etc/subgid 2>/dev/null || printf 'shisae2e:100000:65536\n' >>/etc/subgid
      mkdir -p /run/user/1000
      chown shisae2e:shisae2e /run/user/1000
      su - shisae2e -c 'XDG_RUNTIME_DIR=/run/user/1000 podman info >/dev/null 2>&1' || skip_or_fail "rootless podman is not usable in this container"
    else
      podman info >/dev/null 2>&1 || skip_or_fail "rootless podman is not usable in this container"
    fi
    ;;
  distrobox)
    need_tool distrobox
    distrobox --version >/dev/null
    export CONTAINER_ID="${CONTAINER_ID:-shisa-distrobox-e2e}"
    ;;
  wayland-sway)
    need_tool sway
    export WLR_BACKENDS=headless
    export WLR_RENDERER=pixman
    mkdir -p "$xdg_runtime"
    chmod 700 "$xdg_runtime"
    export XDG_RUNTIME_DIR="$xdg_runtime"
    sway >/tmp/shisa-sway.log 2>&1 &
    sway_pid=$!
    sleep 2
    kill -0 "$sway_pid" >/dev/null 2>&1 || skip_or_fail "headless sway failed to start"
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
    ;;
  *)
    skip_or_fail "unknown hardening scenario: $scenario"
    ;;
esac

mkdir -p "$repo" "$home" "$xdg_config/shisa" "$xdg_cache" "$xdg_runtime"
chmod 700 "$xdg_runtime"
runtime_type="$(stat -f -c %T "$xdg_runtime" 2>/dev/null || true)"
[[ "$runtime_type" == "tmpfs" ]] || skip_or_fail "XDG_RUNTIME_DIR must resolve under tmpfs, got ${runtime_type:-unknown}"

cat >"$xdg_config/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["cwd", "git_branch"]

[modules.git_branch]
show_dirty = true
EOF

git -C "$repo" init -q -b main
printf 'base\n' >"$repo/tracked.txt"
git -C "$repo" add tracked.txt
git -C "$repo" -c user.name=shisa -c user.email=shisa@example.invalid commit -q -m base
printf 'dirty\n' >"$repo/dirty.txt"

zig build --seed 0 debug --summary none --cache-dir "$zig_cache" --global-cache-dir "$zig_global_cache"

env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" \
  "$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'hardening-e2e: shisad socket not ready\n' >&2
  cat "$log" >&2 || true
  exit 1
}

prompt="$(env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" \
  "$root/zig-out/bin/shisa" prompt --socket "$sock" --shell zsh --cwd "$repo" --no-async)"
[[ -n "$prompt" ]] || {
  printf 'hardening-e2e: prompt output was empty\n' >&2
  exit 1
}

env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" \
  "$root/zig-out/bin/shisa" doctor --socket "$sock" >/dev/null

printf 'hardening-e2e: %s/%s ok socket=%s\n' "${SHISA_E2E_DISTRO:-unknown}" "$scenario" "$sock"
