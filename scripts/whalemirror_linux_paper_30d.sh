#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "whalemirror_linux_paper_30d.sh must run on the always-on Linux validation host." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE_ROOT="${WHALEMIRROR_GATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates}"
STATE_DIR="${WHALEMIRROR_GATE_STATE_DIR:-$GATE_ROOT/state}"
REPORT_DIR="${WHALEMIRROR_GATE_REPORT_DIR:-$GATE_ROOT/reports}"
EVIDENCE_PATH="${WHALEMIRROR_PAPER_EVIDENCE:-$REPORT_DIR/paper-evidence.json}"

mkdir -p "$STATE_DIR" "$REPORT_DIR"

if [[ ! -f "$EVIDENCE_PATH" ]]; then
  echo "missing 30-day paper evidence JSON: $EVIDENCE_PATH" >&2
  echo "see docs/whalemirror-paper-30d-runbook.md" >&2
  exit 2
fi

cd "$ROOT_DIR"

reset_args=()
if [[ "${WHALEMIRROR_PAPER_RESET:-0}" == "1" ]]; then
  reset_args+=(--reset)
fi

exec env PYTHONPATH=src uv run stonks-cli whalemirror gates paper-record \
  --evidence "$EVIDENCE_PATH" \
  --state-dir "$STATE_DIR" \
  --report "$REPORT_DIR/paper-gate.md" \
  "${reset_args[@]}"
