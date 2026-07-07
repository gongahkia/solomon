#!/usr/bin/env bash
set -euo pipefail

: "${STONKS_CLI_CARRY_STATE_DIR:=/var/lib/stonks-cli/carry-paper}"
: "${STONKS_CLI_CARRY_DURATION_HOURS:=24}"
: "${STONKS_CLI_CARRY_LOG_DIR:=/var/log/stonks-cli}"
: "${STONKS_CLI_CARRY_INTERVAL_SECONDS:=300}"

mkdir -p "$STONKS_CLI_CARRY_STATE_DIR" "$STONKS_CLI_CARRY_LOG_DIR"

if command -v stonks-cli >/dev/null 2>&1; then
  STONKS_CLI_BIN=(stonks-cli)
elif command -v uv >/dev/null 2>&1; then
  STONKS_CLI_BIN=(uv run stonks-cli)
else
  echo "missing stonks-cli or uv" >&2
  exit 127
fi

while true; do
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  run_dir="$STONKS_CLI_CARRY_STATE_DIR/runs/$run_id"
  mkdir -p "$run_dir"

  "${STONKS_CLI_BIN[@]}" carry health \
    --state-dir "$STONKS_CLI_CARRY_STATE_DIR" \
    --ledger "$STONKS_CLI_CARRY_STATE_DIR/latest-ledger.md" \
    --stream-heartbeat "$STONKS_CLI_CARRY_STATE_DIR/carry-stream-heartbeat.json" \
    --reconciliation "$STONKS_CLI_CARRY_STATE_DIR/latest-reconciliation.md" \
    --json

  "${STONKS_CLI_BIN[@]}" carry paper run \
    --asset BTC \
    --asset ETH \
    --duration-hours "$STONKS_CLI_CARRY_DURATION_HOURS" \
    --state-dir "$run_dir" \
    --report "$run_dir/report.md" \
    --ledger "$run_dir/ledger.md"

  ln -sfn "$run_dir/report.md" "$STONKS_CLI_CARRY_STATE_DIR/latest-report.md"
  ln -sfn "$run_dir/ledger.md" "$STONKS_CLI_CARRY_STATE_DIR/latest-ledger.md"
  ln -sfn "$run_dir/carry-paper-state.json" "$STONKS_CLI_CARRY_STATE_DIR/latest-state.json"

  sleep "$STONKS_CLI_CARRY_INTERVAL_SECONDS"
done
