#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/target/release-gate.json"
cd "$ROOT"

node scripts/ci/mcp-compatibility.mjs
python3 benchmarks/test_pilot_evaluator.py
bash scripts/ci/acceptance-suite.sh smoke
cargo run -p shibahama-perf --release --bin record_perf -- --tiers 100k --queries 3 --output-dir target/release-gate-perf
python3 - "$OUT" <<'PY'
import json,pathlib,sys
path=pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps({"schema_version":1,"passed":True,"required_checks":["mcp-compatibility","pilot-evaluator","contract-and-security-acceptance","100k-local-store-budget"],"external_prerequisites":{"skipped":[{"issue":f"#{n}","reason":"release-owner or registry/archive credentials required"} for n in range(4,9)]}},indent=2)+"\n")
PY
printf 'release gate passed: %s\n' "$OUT"
