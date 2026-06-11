#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

python - <<'PY'
from pathlib import Path

root = Path("bindings/python")
readme = root / "README.md"

assert root.is_dir(), "bindings/python directory is missing"
assert readme.is_file(), "bindings/python README.md is missing"
assert "Python" in readme.read_text(encoding="utf-8")

print("python binding lane present")
PY
