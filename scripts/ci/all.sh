#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

scripts/ci/rust.sh
scripts/ci/server-smoke.sh
scripts/ci/python-binding-smoke.sh
scripts/ci/node-binding-smoke.sh
python3 scripts/ci/correctness-smoke.py

(
  cd tideline
  npm install --silent
  npm run build --silent
)
