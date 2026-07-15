#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TIER="${1:-smoke}"
cd "$ROOT"

bash scripts/ci/service-load-smoke.sh
cargo test -p shibahama-core routing
bash scripts/ci/rbac-smoke.sh
bash scripts/ci/semantic-erasure-smoke.sh

if [[ "$TIER" == full ]]; then
  bash scripts/ci/team-compose-smoke.sh
  cargo run -p shibahama-perf --release --bin record_perf -- --tiers 100k --queries 10 --output-dir target/acceptance-perf
elif [[ "$TIER" != smoke ]]; then
  echo "usage: $0 [smoke|full]" >&2
  exit 2
fi

printf 'acceptance-suite tier=%s deterministic_components=service-load,shard-routing,rbac,semantic-erasure\n' "$TIER"
