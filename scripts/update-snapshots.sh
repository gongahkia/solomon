#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm" || "${2:-}" != "update-snapshots" || "$#" -ne 2 ]]; then
  printf 'usage: scripts/update-snapshots.sh --confirm update-snapshots\n' >&2
  printf 'refusing to write snapshots without explicit confirmation\n' >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

zig build debug --summary none

tmpdir="$(mktemp -d /tmp/shisa-snapshot-update.XXXXXX)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

./zig-out/bin/shisa import-starship test/fixtures/migration/starship/representative.toml >test/snapshots/migration/starship.toml

(
  cd "$tmpdir"
  "$root/zig-out/bin/shisa" import-p10k "$root/test/fixtures/migration/p10k/representative.p10k.zsh" >"$root/test/snapshots/migration/p10k.toml"
  rm -f migration-notes.md
  "$root/zig-out/bin/shisa" import-oh-my-posh "$root/test/fixtures/migration/oh-my-posh/representative.omp.json" >"$root/test/snapshots/migration/oh-my-posh.toml"
  cp oh-my-posh-theme.toml "$root/test/snapshots/migration/oh-my-posh-theme.toml"
  rm -f migration-notes.md
  "$root/zig-out/bin/shisa" import-tide "$root/test/fixtures/migration/tide/representative.fish" >"$root/test/snapshots/migration/tide.toml"
  rm -f migration-notes.md
)

./zig-out/bin/shisa import-pure >test/snapshots/migration/pure.toml

SHISA_UPDATE_SNAPSHOTS=update-snapshots zig build test --summary none
