#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
THRESHOLD_NS="${SHIBAHAMA_PERF_SMOKE_P99_NS:-500000000}"

cd "$ROOT"

cargo run -p shibahama-perf --release --bin record_perf -- \
  --tiers 1k \
  --queries 10 \
  --max-recall-p99-ns "$THRESHOLD_NS" \
  --output-dir target/perf-smoke
