#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
expected="$root/test/snapshots/migration"
tmpdir="$(mktemp -d /tmp/shisa-migration-snapshots.XXXXXX)"

cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

"$root/zig-out/bin/shisa" import-starship "$root/test/fixtures/migration/starship/representative.toml" >"$tmpdir/starship.toml"

(
  cd "$tmpdir"
  "$root/zig-out/bin/shisa" import-p10k "$root/test/fixtures/migration/p10k/representative.p10k.zsh" >p10k.toml
  rm -f migration-notes.md
  "$root/zig-out/bin/shisa" import-oh-my-posh "$root/test/fixtures/migration/oh-my-posh/representative.omp.json" >oh-my-posh.toml
  rm -f migration-notes.md
  "$root/zig-out/bin/shisa" import-tide "$root/test/fixtures/migration/tide/representative.fish" >tide.toml
  rm -f migration-notes.md
)

"$root/zig-out/bin/shisa" import-pure >"$tmpdir/pure.toml"

diff -u "$expected/starship.toml" "$tmpdir/starship.toml"
diff -u "$expected/p10k.toml" "$tmpdir/p10k.toml"
diff -u "$expected/oh-my-posh.toml" "$tmpdir/oh-my-posh.toml"
diff -u "$expected/oh-my-posh-theme.toml" "$tmpdir/oh-my-posh-theme.toml"
diff -u "$expected/tide.toml" "$tmpdir/tide.toml"
diff -u "$expected/pure.toml" "$tmpdir/pure.toml"
