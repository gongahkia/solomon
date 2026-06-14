# Solomon TypeScript SDK

Typed client for Solomon MCP tools over streamable HTTP.

```ts
import { SolomonClient } from "@solomon/sdk";

const solomon = new SolomonClient({
  endpoint: "http://127.0.0.1:8141/mcp",
  token: process.env.SOLOMON_MCP_BEARER_TOKEN,
});

const context = await solomon.preflightContext({
  query: "structure X regulation",
  matter_id: "matter-a",
});

console.log(context.items);
```

Start the server:

```bash
uv run solomon mcp serve --http --host 127.0.0.1 --port 8141
```

The client also accepts SSE-framed JSON-RPC responses from the streamable HTTP endpoint.
