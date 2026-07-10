#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT"

cargo test -p shibahama-python --test wrapper
cargo test -p shibahama-node --test wrapper
scripts/ci/python-binding-smoke.sh
scripts/ci/node-binding-smoke.sh
