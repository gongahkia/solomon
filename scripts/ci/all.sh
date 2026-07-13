#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

scripts/ci/rust.sh
bash scripts/ci/mcp-conformance.sh
scripts/ci/binding-parity.sh
node scripts/ci/sdk-contract.mjs
node scripts/ci/claude-code-mcp-fixture.mjs
node scripts/ci/codex-mcp-fixture.mjs
node scripts/ci/pi-mcp-fixture.mjs
scripts/ci/golden-parity.sh
python3 scripts/ci/correctness-smoke.py

(
  cd tideline
  npm install --silent
  npm run build --silent
)
