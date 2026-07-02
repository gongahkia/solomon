#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cd "$ROOT"

"$PYTHON_BIN" -m venv "$tmpdir/venv"
export VIRTUAL_ENV="$tmpdir/venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

python -m pip install --disable-pip-version-check --quiet --upgrade pip
python -m pip install --disable-pip-version-check --quiet maturin==1.13.3

(
  cd bindings/python
  python -m maturin develop --quiet
)

(
  cd bindings/node
  npm ci --silent
  npm run build --silent
)

python scripts/ci/golden-parity.py
