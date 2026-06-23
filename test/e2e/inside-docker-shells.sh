#!/usr/bin/env bash
set -euo pipefail

root=/src
shells="${SHISA_E2E_SHELLS:-bash,zsh,fish}"
tmp="$(mktemp -d /tmp/shisa-e2e.XXXXXX)"
repo="$tmp/repo"
sock="$tmp/shisa.sock"
log="$tmp/shisad.log"
home="$tmp/home"
xdg_config="$tmp/config"
xdg_cache="$tmp/cache"
xdg_runtime="$tmp/runtime"
zig_cache="$tmp/zig-cache"
zig_global_cache="$tmp/zig-global-cache"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

contains_git_prompt() {
  case "$1" in
    *git:main\**) return 0 ;;
    *) printf 'docker-e2e: expected git:main* in output, got: %s\n' "$1" >&2; return 1 ;;
  esac
}

mkdir -p "$repo" "$home" "$xdg_config/shisa" "$xdg_cache" "$xdg_runtime"
chmod 700 "$xdg_runtime"
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
  printf 'docker-e2e: shisad socket not ready\n' >&2
  cat "$log" >&2 || true
  exit 1
}

env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" \
  "$root/zig-out/bin/shisa" prompt --socket "$sock" --shell zsh --cwd "$repo" --no-async >/dev/null

IFS=, read -r -a shell_list <<<"$shells"
for shell_name in "${shell_list[@]}"; do
  case "$shell_name" in
    bash)
      output="$(env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" bash --noprofile --norc -c "cd '$repo'; source '$root/init/shisa.bash'; shisa_prompt_render")"
      ;;
    zsh)
      output="$(env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" zsh -fc "cd '$repo'; source '$root/init/shisa.zsh'; shisa_prompt_render")"
      ;;
    fish)
      output="$(env HOME="$home" XDG_CONFIG_HOME="$xdg_config" XDG_CACHE_HOME="$xdg_cache" XDG_RUNTIME_DIR="$xdg_runtime" SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" fish --no-config -c "cd '$repo'; source '$root/init/shisa.fish'; shisa_prompt_render")"
      ;;
    *)
      printf 'docker-e2e: unknown shell in matrix: %s\n' "$shell_name" >&2
      exit 1
      ;;
  esac
  contains_git_prompt "$output"
  printf 'docker-e2e: %s/%s ok\n' "${SHISA_E2E_DISTRO:-unknown}" "$shell_name"
done
