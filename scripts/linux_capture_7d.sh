#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "linux_capture_7d.sh must run on the always-on Linux validation host." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE_ROOT="${STONKS_CLI_VALIDATION_GATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/validation-gates}"
STATE_DIR="${STONKS_CLI_VALIDATION_GATE_STATE_DIR:-$GATE_ROOT/state}"
REPORT_DIR="${STONKS_CLI_VALIDATION_GATE_REPORT_DIR:-$GATE_ROOT/reports}"
CAPTURE_DIR="${STONKS_CLI_VALIDATION_GATE_CAPTURE_DIR:-$GATE_ROOT/captures}"
LOG_DIR="${STONKS_CLI_VALIDATION_GATE_LOG_DIR:-$GATE_ROOT/logs}"

DURATION_SECONDS="${STONKS_CLI_CAPTURE_DURATION_SECONDS:-604800}"
COINS="${STONKS_CLI_CAPTURE_COINS:-BTC ETH SOL}"
USER_FILL_WALLETS="${STONKS_CLI_USER_FILL_WALLETS:-}"
USER_FUNDING_WALLETS="${STONKS_CLI_USER_FUNDING_WALLETS:-}"
HEARTBEAT_SECONDS="${STONKS_CLI_CAPTURE_HEARTBEAT_SECONDS:-30}"
HEALTH_INTERVAL_SECONDS="${STONKS_CLI_CAPTURE_HEALTH_INTERVAL_SECONDS:-300}"

mkdir -p "$STATE_DIR" "$REPORT_DIR" "$CAPTURE_DIR" "$LOG_DIR"
cd "$ROOT_DIR"

coin_args=()
for coin in $COINS; do
  coin_args+=(--coin "$coin")
done

wallet_args=()
for wallet in $USER_FILL_WALLETS; do
  wallet_args+=(--user-fill-wallet "$wallet")
done
for wallet in $USER_FUNDING_WALLETS; do
  wallet_args+=(--user-funding-wallet "$wallet")
done

extra_args=()
if [[ "${STONKS_CLI_CAPTURE_ALL_MIDS:-1}" == "0" ]]; then
  extra_args+=(--no-all-mids)
else
  extra_args+=(--all-mids)
fi
if [[ -n "${STONKS_CLI_CAPTURE_ALL_MIDS_DEX:-}" ]]; then
  extra_args+=(--all-mids-dex "$STONKS_CLI_CAPTURE_ALL_MIDS_DEX")
fi
if [[ -n "${STONKS_CLI_CAPTURE_MAX_RECONNECTS:-}" ]]; then
  extra_args+=(--max-reconnects "$STONKS_CLI_CAPTURE_MAX_RECONNECTS")
fi
if [[ -n "${STONKS_CLI_CAPTURE_STOP_AFTER_MESSAGES:-}" ]]; then
  extra_args+=(--stop-after-messages "$STONKS_CLI_CAPTURE_STOP_AFTER_MESSAGES")
fi
if [[ "${STONKS_CLI_CAPTURE_RESET:-0}" == "1" ]]; then
  extra_args+=(--reset)
fi

exec env PYTHONPATH=src uv run stonks-cli run-ingest \
  "${coin_args[@]}" \
  "${wallet_args[@]}" \
  "${extra_args[@]}" \
  --duration-seconds "$DURATION_SECONDS" \
  --heartbeat-seconds "$HEARTBEAT_SECONDS" \
  --health-interval-seconds "$HEALTH_INTERVAL_SECONDS" \
  --state-dir "$STATE_DIR" \
  --raw-out "$CAPTURE_DIR/hyperliquid-raw.jsonl" \
  --out "$CAPTURE_DIR/hyperliquid-normalized.jsonl" \
  --health "$REPORT_DIR/capture-health.json" \
  --report "$REPORT_DIR/capture-gate.md"
