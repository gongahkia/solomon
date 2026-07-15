#!/usr/bin/env bash
set -euo pipefail

if git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- ':!uv.lock'; then
  echo 'release integrity failed: unresolved merge marker'
  exit 1
fi
uv run python -m compileall -q src
uv run stonks-cli --help >/dev/null
uv run stonks-mcp --help >/dev/null
uv run ruff check src tests scripts
PYTHONPATH=src uv run pytest -q tests
