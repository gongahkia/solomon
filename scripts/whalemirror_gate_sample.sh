#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${WHALEMIRROR_GATE_STATE_DIR:-$ROOT_DIR/.cache/whalemirror-gates/state}"
REPORT_DIR="${WHALEMIRROR_GATE_REPORT_DIR:-$ROOT_DIR/.cache/whalemirror-gates/reports}"
CAPTURE_DIR="${WHALEMIRROR_GATE_CAPTURE_DIR:-$ROOT_DIR/.cache/whalemirror-gates/captures}"

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
