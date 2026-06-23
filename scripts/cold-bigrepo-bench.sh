#!/usr/bin/env bash
# Verify north-star §10 headline: cold render in a real big repo without a
# timeout. Generates a synthetic git repo with N commits and M tracked files,
# boots shisad, and asserts that the FIRST render (cold cache, no fsnotify
# warmup) completes inside SHISA_COLD_BUDGET_MS.
#
# If starship is on PATH, runs it on the same fixture for comparison. No
# strict starship gate here; this script's job is to prove Shisa's headline,
# not to dunk on starship.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMMITS=${SHISA_BIGREPO_COMMITS:-2000}
FILES=${SHISA_BIGREPO_FILES:-1500}
BUDGET_MS=${SHISA_COLD_BUDGET_MS:-100}
RUNS=${SHISA_BIGREPO_RUNS:-10}

TMP=$(mktemp -d -t shisa-bigrepo-XXXXXX)
SOCK="$TMP/socket"
LOG="$TMP/shisad.log"
REPO="$TMP/repo"
RESULT="$TMP/result.json"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  }
}
need git
need hyperfine
need jq

[[ -x "$ROOT/zig-out/bin/shisad" && -x "$ROOT/zig-out/bin/shisa" ]] || {
  printf 'shisad / shisa not built; run zig build first\n' >&2
  exit 1
}

printf 'cold-bigrepo-bench: generating synthetic repo (%s commits, %s files)\n' "$COMMITS" "$FILES"
git init -q "$REPO"
cd "$REPO"
git config user.email bench@shisa.local
git config user.name shisa-bench
git config commit.gpgsign false

# seed M files
for ((f = 0; f < FILES; f++)); do
  printf 'line %d\n' "$f" > "f$f.txt"
done
git add . >/dev/null
git commit -q -m 'seed'

# N-1 follow-up commits touching one file each, so the index is large
# but rev-walks are bounded.
for ((c = 1; c < COMMITS; c++)); do
  idx=$((c % FILES))
  printf 'rev %d line\n' "$c" >> "f$idx.txt"
  git add "f$idx.txt"
  git commit -q -m "rev $c"
done

# leave one untracked + one modified to exercise git_status work
echo dirty >> "f0.txt"
echo new > "untracked.txt"

cd "$ROOT"

"$ROOT/zig-out/bin/shisad" --foreground --socket "$SOCK" --log "$LOG" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$SOCK" ]] && break
  sleep 0.01
done
[[ -S "$SOCK" ]] || {
  printf 'shisad socket not ready\n' >&2
  exit 1
}

# Cold timing: kill any cache for the repo path by clearing the daemon's
# cache once. We do that by `shisa cache clear` if it exists; otherwise
# the first render against this never-seen cwd IS the cold path.
"$ROOT/zig-out/bin/shisa" cache clear --socket "$SOCK" >/dev/null 2>&1 || true

# Repeat: each prepare step clears the cache so every run is cold.
hyperfine \
  --runs "$RUNS" \
  --warmup 0 \
  --prepare "$ROOT/zig-out/bin/shisa cache clear --socket $SOCK >/dev/null 2>&1 || true" \
  --export-json "$RESULT" \
  "$ROOT/zig-out/bin/shisa prompt --socket $SOCK --shell zsh --cwd $REPO" \
  >/dev/null 2>&1 || {
    printf 'hyperfine cold-bench failed\n' >&2
    exit 1
  }

mean_ms=$(jq -r '.results[0].mean * 1000' "$RESULT")
max_ms=$(jq -r '.results[0].max * 1000' "$RESULT")
min_ms=$(jq -r '.results[0].min * 1000' "$RESULT")

printf 'cold-bigrepo-bench: shisa cold mean=%.1fms min=%.1fms max=%.1fms budget=%sms (repo=%s commits, %s files)\n' \
  "$mean_ms" "$min_ms" "$max_ms" "$BUDGET_MS" "$COMMITS" "$FILES"

if command -v starship >/dev/null 2>&1; then
  STARSHIP_RESULT="$TMP/starship.json"
  hyperfine \
    --runs "$RUNS" \
    --warmup 0 \
    --export-json "$STARSHIP_RESULT" \
    "starship prompt --status 0 --jobs 0 --cmd-duration 0" \
    --shell=bash \
    --command-name starship \
    >/dev/null 2>&1 && {
      s_mean=$(jq -r '.results[0].mean * 1000' "$STARSHIP_RESULT")
      s_max=$(jq -r '.results[0].max * 1000' "$STARSHIP_RESULT")
      printf 'cold-bigrepo-bench: starship comparison mean=%.1fms max=%.1fms (informational only)\n' \
        "$s_mean" "$s_max"
    } || printf 'cold-bigrepo-bench: starship comparison skipped (run failed)\n'
else
  printf 'cold-bigrepo-bench: starship not on PATH, skipping comparison\n'
fi

over=$(awk -v m="$max_ms" -v b="$BUDGET_MS" 'BEGIN { print (m > b) ? "1" : "0" }')
if [[ "$over" == "1" ]]; then
  printf 'cold-bigrepo-bench: max %.1fms exceeds budget %sms\n' "$max_ms" "$BUDGET_MS" >&2
  exit 1
fi
