#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/src"

if ! command -v polymarket >/dev/null 2>&1; then
  echo "polymarket CLI not installed. Run scripts/install_polymarket_cli.sh first." >&2
  exit 1
fi

echo "[1/8] Rust tests"
(cd "${ROOT}/rust" && cargo test)

echo "[2/8] Python Polymarket tests"
(cd "${ROOT}" && PYTHONPATH=src pytest -q \
  tests/test_polymarket_provider.py \
  tests/test_polymarket_scanner.py \
  tests/test_polymarket_runtime.py \
  tests/test_polymarket_wallets.py \
  tests/test_polymarket_paper.py \
  tests/test_polymarket_runtime_cycle.py \
  tests/test_polymarket_runtime_loop.py \
  tests/test_polymarket_risk.py \
  tests/test_polymarket_exits.py \
  tests/test_polymarket_execution.py \
  tests/test_polymarket_journal.py \
  tests/test_polymarket_stream.py \
  tests/test_polymarket_lifecycle.py \
  tests/test_polymarket_websocket.py \
  tests/test_polymarket_auth.py \
  tests/test_polymarket_guards.py \
  tests/test_polymarket_preflight.py \
  tests/test_polymarket_replay.py \
  tests/test_polymarket_settlement.py \
  tests/test_polymarket_rust_control.py \
  tests/test_polymarket_runtime_rust.py \
  tests/test_polymarket_rust_path.py \
  tests/test_polymarket_heartbeat.py)

echo "[3/8] CLI health"
polymarket status

echo "[4/8] Wallet"
polymarket wallet show
polymarket wallet address

echo "[5/8] Approvals"
polymarket approve check

echo "[6/8] Collateral balance"
polymarket -o json clob balance --asset-type collateral

echo "[7/8] Repo doctor"
(cd "${ROOT}" && python3 - <<'PY'
from stonks_cli.config import load_config
from stonks_cli.polymarket.rust_control import rust_control_call

cfg = load_config()
result = rust_control_call("doctor", args={"deep_auth": True}, cfg=cfg)
import json
print(json.dumps(result, indent=2))
PY
)

echo "[8/8] Read-only market sanity"
polymarket -o json markets list --limit 3
echo "dry run complete"
