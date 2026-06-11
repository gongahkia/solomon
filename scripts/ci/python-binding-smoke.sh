#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

python -m venv "$tmpdir/venv"
export VIRTUAL_ENV="$tmpdir/venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

python -m pip install --disable-pip-version-check --quiet --upgrade pip
python -m pip install --disable-pip-version-check --quiet maturin==1.13.3

(
  cd bindings/python
  python -m maturin develop --quiet
)

python - <<'PY'
import shibahama

assert shibahama.version() == shibahama.__version__
assert shibahama.version()

print("python binding lane passed")
PY
