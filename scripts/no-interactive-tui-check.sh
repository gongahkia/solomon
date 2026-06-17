#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

matches="$(
  git grep -n -E 'termios|raw mode|ncurses|readline|alternate screen|enterAlternateScreen|enableRawMode|cursor-addressing' -- src init 2>/dev/null || true
)"

if [ -z "$matches" ]; then
  echo "no interactive TUI gate: ok"
  exit 0
fi

if printf '%s\n' "$matches" | grep -q -- '--interactive'; then
  echo "no interactive TUI gate: ok"
  exit 0
fi

echo "no interactive TUI gate: raw/full-screen terminal UI requires an explicit --interactive flag"
printf '%s\n' "$matches"
exit 1
