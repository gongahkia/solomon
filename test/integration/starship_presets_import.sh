#!/usr/bin/env bash
set -euo pipefail

if ! command -v starship >/dev/null 2>&1; then
  printf 'skip starship preset import: starship not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
snapshots="$root/test/snapshots/starship-import"
tmpdir="$(mktemp -d /tmp/shisa-starship-presets.XXXXXX)"

cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

while IFS= read -r preset; do
  [[ -n "$preset" ]] || continue
  input="$tmpdir/$preset.starship.toml"
  output="$tmpdir/$preset.shisa.toml"
  expected="$snapshots/$preset.toml"
  starship preset "$preset" -o "$input"
  "$root/zig-out/bin/shisa" import-starship "$input" >"$output"
  diff -u "$expected" "$output"
done < <(starship preset --list)
