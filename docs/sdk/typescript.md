# TypeScript SDK quickstart

The TypeScript SDK targets Solomon's MCP streamable HTTP endpoint and mirrors the MCP tool names with typed camelCase methods.

## Start the MCP HTTP server

```bash
uv run solomon mcp serve --http --host 127.0.0.1 --port 8141
```

If MCP bearer auth is configured, pass the same token to the client.

## Install from the repo

```bash
cd packages/solomon-ts
npm run typecheck
npm run build
```

## Use the client

```ts
import { SolomonClient } from "@solomon/sdk";

const solomon = new SolomonClient({
  endpoint: "http://127.0.0.1:8141/mcp",
  token: process.env.SOLOMON_MCP_BEARER_TOKEN,
});

const context = await solomon.preflightContext({
  query: "structure X regulation",
  matter_id: "matter-a",
  client_id: "client-a",
});

console.log(context.items);
```

## Tool method mapping

| MCP tool | TypeScript method |
| --- | --- |
| `solomon.health` | `health()` |
| `solomon.preflight_context` | `preflightContext()` |
| `solomon.check_currency` | `checkCurrency()` |
| `solomon.get_dependencies` | `getDependencies()` |
| `solomon.verify_position` | `verifyPosition()` |
| `solomon.ingest` | `ingest()` |
| `solomon.audit_pack` | `auditPack()` |
| `solomon.dependency_suggestions` | `dependencySuggestions()` |
| `solomon.impact` | `impact()` |

## Vendor preflight example

```ts
const context = await solomon.preflightContext({
  query: "Can we reuse the Structure X position?",
  max_items: 3,
});

const currentItems = context.items.map((entry) => entry.item);
console.log(currentItems);
```

The SDK parses JSON and SSE-framed JSON-RPC responses from the streamable HTTP MCP endpoint.
