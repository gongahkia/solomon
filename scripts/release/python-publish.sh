#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

target="${1:-testpypi}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dist_dir="$repo_root/dist/python"
tmpdir="$(mktemp -d)"
python_bin="${PYTHON:-python3}"
trap 'rm -rf "$tmpdir"' EXIT

case "$target" in
  testpypi)
    repository_url="https://test.pypi.org/legacy/"
    token_var="TEST_PYPI_TOKEN"
    ;;
  pypi)
    repository_url="https://upload.pypi.org/legacy/"
    token_var="PYPI_TOKEN"
    ;;
  *)
    printf 'usage: %s [testpypi|pypi]\n' "$0" >&2
    exit 2
    ;;
esac

rm -rf "$dist_dir"
mkdir -p "$dist_dir"

"$python_bin" -m venv "$tmpdir/venv"
export VIRTUAL_ENV="$tmpdir/venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

python -m pip install --disable-pip-version-check --quiet --upgrade pip
python -m pip install --disable-pip-version-check --quiet maturin==1.13.3 twine==6.2.0

(
  cd "$repo_root/bindings/python"
  python -m maturin build --release --sdist --out "$dist_dir"
)

python -m twine check "$dist_dir"/*

if [[ "${SHIBAHAMA_PUBLISH:-0}" != "1" ]]; then
  printf 'built and checked Python artifacts in %s\n' "$dist_dir"
  printf 'set SHIBAHAMA_PUBLISH=1 and %s to upload to %s\n' "$token_var" "$target"
  exit 0
fi

token="${!token_var:-}"
if [[ -z "$token" ]]; then
  printf '%s is required to publish to %s\n' "$token_var" "$target" >&2
  exit 1
fi

python -m twine upload \
  --repository-url "$repository_url" \
  --username __token__ \
  --password "$token" \
  "$dist_dir"/*
