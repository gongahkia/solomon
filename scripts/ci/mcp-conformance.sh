#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output="${SHIBAHAMA_MCP_CONFORMANCE_OUTPUT:-$ROOT/target/mcp-conformance.json}"
mkdir -p "$(dirname "$output")"

run_case() {
  local name="$1"
  shift
  if "$@"; then
    printf '%s\n' "$name: passed"
    return 0
  fi
  printf '%s\n' "$name: failed" >&2
  return 1
}

stdio=false
http=false
protocol=false
if run_case protocol_dispatch cargo test -p shibahama-cli mcp::tests::rejects_malformed_requests_and_ignores_cancellation_notifications; then
  protocol=true
fi
if run_case stdio bash "$ROOT/scripts/ci/mcp-stdio-smoke.sh"; then
  stdio=true
fi
if run_case http bash "$ROOT/scripts/ci/server-smoke.sh"; then
  http=true
fi

python3 - "$output" "$protocol" "$stdio" "$http" <<'PY'
import json
import sys

path, protocol, stdio, http = sys.argv[1:]
report = {
    "schemaVersion": 1,
    "suite": "mcp-conformance",
    "transports": {
        "stdio": stdio == "true",
        "streamableHttp": http == "true",
    },
    "protocolDispatcher": protocol == "true",
    "cases": [
        "invalid_json",
        "cancelled_notification",
        "scope_escalation",
        "missing_destructive_confirmation",
        "confirmation_token_replay",
        "actor_class_spoofing",
    ],
    "passed": protocol == "true" and stdio == "true" and http == "true",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(report, handle, sort_keys=True)
    handle.write("\n")
PY

if [[ "$protocol" != true || "$stdio" != true || "$http" != true ]]; then
  exit 1
fi

echo "MCP conformance passed: $output"
