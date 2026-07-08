#!/usr/bin/env bash
set -euo pipefail

if ! command -v nix-shell >/dev/null 2>&1; then
  printf 'skip nix-shell language integration: nix-shell not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="/tmp/shisa-nix-lang-$$"
sock="$tmp/shisa.sock"
log="$tmp/shisad.log"
repo="$tmp/repo"
xdg="$tmp/xdg"
fake_bin="$tmp/bin"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p "$repo" "$xdg/shisa" "$fake_bin"
cat >"$repo/pyproject.toml" <<'EOF'
[project]
name = "shisa-nix-lang"
EOF
cat >"$xdg/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["language_versions"]

[modules.language_versions]
detect = ["python"]
path_hash_invalidate = true
EOF
cat >"$fake_bin/python3" <<'EOF'
#!/bin/sh
echo Python 3.10.0
EOF
chmod 755 "$fake_bin/python3"

(cd "$root" && zig build debug)
PATH="$fake_bin:$PATH" "$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'shisad socket not ready\n' >&2
  exit 1
}

render_outer() {
  PATH="$fake_bin:$PATH" XDG_CONFIG_HOME="$xdg" "$root/zig-out/bin/shisa" prompt --socket "$sock" --cwd "$repo" --shell zsh --cols 80 --rows 24
}

outer=""
for _ in {1..100}; do
  outer="$(render_outer)"
  [[ "$outer" == *"lang:py:3.10.0"* ]] && break
  sleep 0.02
done
[[ "$outer" == *"lang:py:3.10.0"* ]]

inside_cmd="env XDG_CONFIG_HOME=$(printf '%q' "$xdg") $(printf '%q' "$root/zig-out/bin/shisa") prompt --socket $(printf '%q' "$sock") --cwd $(printf '%q' "$repo") --shell zsh --cols 80 --rows 24"
inside_once="$(nix-shell -p python311 --run "$inside_cmd")"
[[ "$inside_once" != *"lang:py:3.10.0"* ]]

inside=""
for _ in {1..100}; do
  inside="$(nix-shell -p python311 --run "$inside_cmd")"
  [[ "$inside" =~ lang:py:3\.11\. ]] && break
  sleep 0.02
done
[[ "$inside" =~ lang:py:3\.11\. ]]
