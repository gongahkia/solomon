#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cat <<'EOF' | cargo run -q -p shibahama-cli --manifest-path "$ROOT/shibahama-cli/Cargo.toml" -- mcp --path "$tmpdir/mcp-stdio.redb" --dimensions 2 --scope-repository smoke --scope-visibility repository --principal smoke-agent | python3 -c 'import json,sys
responses = [json.loads(line) for line in sys.stdin]
assert len(responses) == 3
assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
assert len(responses[1]["result"]["tools"]) == 7
write = responses[2]["result"]
assert write["isError"] is False
assert write["structuredContent"]["result"]["memory"]["provenance"]["ingested_by"] == "smoke-agent"'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"shibahama_memory_write_v1","arguments":{"schemaVersion":1,"scope":{"repository":"smoke","team":null,"visibility":"repository"},"actor":"human","actorId":"smoke-agent","content":"stdio MCP memory","vector":[1,0],"sourceKind":"user","validFromUnix":0,"ingestedAtUnix":0}}}
EOF

echo "MCP stdio smoke passed"
