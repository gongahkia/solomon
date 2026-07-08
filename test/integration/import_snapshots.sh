#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
expected="$root/test/snapshots/migration"
tmpdir="$(mktemp -d /tmp/shisa-import-snapshots.XXXXXX)"
shisa="$root/zig-out/bin/shisa"

cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

"$shisa" import-starship "$root/test/fixtures/migration/starship/representative.toml" --dry-run --no-warn-unmapped >"$tmpdir/starship.toml"
"$shisa" import-p10k "$root/test/fixtures/migration/p10k/representative.p10k.zsh" --dry-run --no-warn-unmapped >"$tmpdir/p10k.toml"
"$shisa" import-tide "$root/test/fixtures/migration/tide/representative.fish" --dry-run --no-warn-unmapped >"$tmpdir/tide.toml"
"$shisa" import-pure --dry-run >"$tmpdir/pure.toml"

"$shisa" import-oh-my-posh "$root/test/fixtures/migration/oh-my-posh/representative.omp.json" --output "$tmpdir/oh-my-posh.toml" --no-warn-unmapped

diff -u "$expected/starship.toml" "$tmpdir/starship.toml"
diff -u "$expected/p10k.toml" "$tmpdir/p10k.toml"
diff -u "$expected/oh-my-posh.toml" "$tmpdir/oh-my-posh.toml"
diff -u "$expected/oh-my-posh-theme.toml" "$tmpdir/oh-my-posh-theme.toml"
diff -u "$expected/tide.toml" "$tmpdir/tide.toml"
diff -u "$expected/pure.toml" "$tmpdir/pure.toml"

"$shisa" import-starship "$root/test/fixtures/migration/starship/representative.toml" --dry-run >"$tmpdir/warnings.out"
grep -q '# Migration warnings' "$tmpdir/warnings.out"
grep -q 'battery.*custom module or plugin' "$tmpdir/warnings.out"
grep -q 'docs/migration-starship.md' "$tmpdir/warnings.out"

mkdir -p "$tmpdir/config/shisa"
printf 'version = 1\n' >"$tmpdir/config/shisa/shisa.toml"
XDG_CONFIG_HOME="$tmpdir/config" "$shisa" import-starship "$root/test/fixtures/migration/starship/representative.toml" --diff >"$tmpdir/diff.out"
grep -q '^--- .*shisa.toml' "$tmpdir/diff.out"
grep -q '^+++ imported' "$tmpdir/diff.out"
grep -q '^+theme = "plain"' "$tmpdir/diff.out"
test "$(cat "$tmpdir/config/shisa/shisa.toml")" = "version = 1"

"$shisa" import-pure --output "$tmpdir/out/shisa.toml" >"$tmpdir/pure-write.out"
test -s "$tmpdir/out/shisa.toml"
test ! -s "$tmpdir/pure-write.out"
