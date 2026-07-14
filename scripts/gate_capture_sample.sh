#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" == "Linux" ]]; then
  DEFAULT_GATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/validation-gates"
else
  DEFAULT_GATE_ROOT="$ROOT_DIR/.cache/validation-gates"
fi

GATE_ROOT="${STONKS_CLI_VALIDATION_GATE_ROOT:-$DEFAULT_GATE_ROOT}"
STATE_DIR="${STONKS_CLI_VALIDATION_GATE_STATE_DIR:-$GATE_ROOT/state}"
REPORT_DIR="${STONKS_CLI_VALIDATION_GATE_REPORT_DIR:-$GATE_ROOT/reports}"
CAPTURE_DIR="${STONKS_CLI_VALIDATION_GATE_CAPTURE_DIR:-$GATE_ROOT/captures}"

cd "$ROOT_DIR"
mkdir -p "$STATE_DIR" "$REPORT_DIR" "$CAPTURE_DIR"

PYTHONPATH=src uv run stonks-cli sample-capture-gate \
  --state-dir "$STATE_DIR" \
  --capture-out-dir "$CAPTURE_DIR" \
  --report "$REPORT_DIR/capture-gate.md"

PYTHONPATH=src uv run stonks-cli status-gate \
  --state-dir "$STATE_DIR"
