#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" == "Linux" ]]; then
  DEFAULT_GATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates"
else
  DEFAULT_GATE_ROOT="$ROOT_DIR/.cache/whalemirror-gates"
fi

GATE_ROOT="${WHALEMIRROR_GATE_ROOT:-$DEFAULT_GATE_ROOT}"
STATE_DIR="${WHALEMIRROR_GATE_STATE_DIR:-$GATE_ROOT/state}"
REPORT_DIR="${WHALEMIRROR_GATE_REPORT_DIR:-$GATE_ROOT/reports}"
CAPTURE_DIR="${WHALEMIRROR_GATE_CAPTURE_DIR:-$GATE_ROOT/captures}"

cd "$ROOT_DIR"
mkdir -p "$STATE_DIR" "$REPORT_DIR" "$CAPTURE_DIR"

PYTHONPATH=src uv run stonks-cli whalemirror gates capture-sample \
  --state-dir "$STATE_DIR" \
  --capture-out-dir "$CAPTURE_DIR" \
  --report "$REPORT_DIR/capture-gate.md"

PYTHONPATH=src uv run stonks-cli whalemirror gates paper-sample \
  --state-dir "$STATE_DIR" \
  --report "$REPORT_DIR/paper-gate.md"

PYTHONPATH=src uv run stonks-cli whalemirror gates live-sample \
  --state-dir "$STATE_DIR" \
  --report "$REPORT_DIR/live-gate.md"

PYTHONPATH=src uv run stonks-cli whalemirror gates status \
  --state-dir "$STATE_DIR"
