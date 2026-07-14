#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

scripts/ci/rust.sh
bash scripts/ci/mcp-conformance.sh
bash scripts/ci/admin-bootstrap-smoke.sh
bash scripts/ci/rbac-smoke.sh
bash scripts/ci/service-token-smoke.sh
bash scripts/ci/cors-smoke.sh
bash scripts/ci/rate-limit-smoke.sh
bash scripts/ci/semantic-erasure-smoke.sh
scripts/ci/binding-parity.sh
node scripts/ci/mcp-compatibility.mjs
scripts/ci/golden-parity.sh
python3 scripts/ci/correctness-smoke.py

(
  cd tideline
  npm install --silent
  npm run build --silent
)
