#!/usr/bin/env bash
# Measure end-to-end render latency (shell-binary startup + socket roundtrip
# + render + result write) and fail if p99 exceeds the budget.
#
# Rationale: north-star §10 warm p99 < 2 ms target measures pure render, not
# the user-visible end-to-end shell-binary path. This gate uses a tighter
# but still debug-safe budget (default 10 ms p99) to surface regressions in
# the path the user actually experiences. Tighten as warm-path work removes overhead.
#
# Empirical baseline (Apple Silicon, 2026-06): default debug build 200 runs
# mean ~3.0 ms, p99 3.5-4.3 ms; ReleaseFast mean 2.32 ms, p99 3.33 ms.
# Daemon metrics show the warm render itself is sub-100us in 199/200 samples.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BUDGET_MS=${SHISA_RENDER_P99_BUDGET_MS:-10}
RUNS=${SHISA_RENDER_P99_RUNS:-200}
WARMUP=${SHISA_RENDER_P99_WARMUP:-20}
SOCK="${TMPDIR:-/tmp}/shisa-p99-$$.sock"
LOG="${TMPDIR:-/tmp}/shisa-p99-$$.log"
OUT_JSON="${TMPDIR:-/tmp}/shisa-p99-$$.json"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  }
}

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$SOCK" "$LOG" "$OUT_JSON"
}
trap cleanup EXIT

need hyperfine
need jq
[[ -x "$ROOT/zig-out/bin/shisad" && -x "$ROOT/zig-out/bin/shisa" ]] || {
  printf 'shisad / shisa not built; run zig build first\n' >&2
  exit 1
}

"$ROOT/zig-out/bin/shisad" --foreground --socket "$SOCK" --log "$LOG" >/dev/null 2>&1 &
daemon_pid=$!

for _ in {1..100}; do
  [[ -S "$SOCK" ]] && break
  sleep 0.01
done
[[ -S "$SOCK" ]] || {
  printf 'shisad socket not ready\n' >&2
  exit 1
}

hyperfine \
  --shell=none \
  --warmup "$WARMUP" \
  --runs "$RUNS" \
  --export-json "$OUT_JSON" \
  "$ROOT/zig-out/bin/shisa prompt --socket $SOCK --shell zsh --cwd /tmp" \
  >/dev/null 2>&1 || {
  printf 'hyperfine run failed\n' >&2
  exit 1
}

# hyperfine reports each run in seconds under .results[0].times
p99_ms=$(jq -r '.results[0].times | sort | .[(length * 99 / 100 | floor)] * 1000' "$OUT_JSON")
mean_ms=$(jq -r '.results[0].mean * 1000' "$OUT_JSON")
max_ms=$(jq -r '.results[0].max * 1000' "$OUT_JSON")

printf 'render-p99-gate: runs=%s mean=%.2fms max=%.2fms p99=%.2fms budget=%sms\n' \
  "$RUNS" "$mean_ms" "$max_ms" "$p99_ms" "$BUDGET_MS"

# bash can't do float compare; use awk
over=$(awk -v p="$p99_ms" -v b="$BUDGET_MS" 'BEGIN { print (p > b) ? "1" : "0" }')
if [[ "$over" == "1" ]]; then
  printf 'render-p99-gate: p99 %.2fms exceeds budget %sms\n' "$p99_ms" "$BUDGET_MS" >&2
  exit 1
fi
