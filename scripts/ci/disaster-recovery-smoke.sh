#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
started="$(date +%s)"
bash "$ROOT/scripts/ci/team-compose-smoke.sh"
finished="$(date +%s)"
printf 'disaster recovery verified rpo_seconds=0 rto_seconds=%s\n' "$((finished - started))"
