#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [ ! -x ./zig-out/bin/shisa ]; then
  zig build debug --summary none
fi

found=0
for theme in themes/*.toml; do
  [ -e "$theme" ] || continue
  found=1
  ./zig-out/bin/shisa theme validate "$theme"
done

[ "$found" -eq 1 ] || {
  echo "theme contrast gate: no themes found" >&2
  exit 1
}
