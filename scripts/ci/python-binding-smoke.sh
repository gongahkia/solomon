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
import tempfile
from pathlib import Path

import shibahama

assert shibahama.version() == shibahama.__version__
assert shibahama.version()
assert (Path("bindings/python/python/shibahama/__init__.pyi")).is_file()
assert (Path("bindings/python/python/shibahama/py.typed")).is_file()

with tempfile.NamedTemporaryFile() as db:
    engine = shibahama.Shibahama(db.name, 2)
    item = engine.write(
        "Python binding memory",
        vector=[0.0, 0.0],
        source_kind="user",
        source_ref="smoke",
        valid_from_unix=0,
        ingested_at_unix=0,
    )
    recalled = engine.recall([0.0, 0.0], 1, now_unix=0)
    streamed = engine.stream_recall([0.0, 0.0], 1, now_unix=0)
    timeline = engine.timeline([0.0, 0.0], 1, as_of_unix=0)
    why = engine.why(item.id, now_unix=0)

    assert item.content == "Python binding memory"
    assert recalled[0].id == item.id
    assert next(streamed).id == item.id
    assert timeline[0].id == item.id
    assert engine.reinforce(item.id, "cited")
    assert why is not None
    assert why.item.id == item.id

print("python binding lane passed")
PY
