<!-- SPDX-License-Identifier: Apache-2.0 -->

# TypeScript SDK examples

Start the MCP HTTP server:

```bash
uv run solomon mcp serve --http --host 127.0.0.1 --port 8141
```

Use the SDK:

```ts
import { SolomonClient } from "@solomon/sdk";

const client = new SolomonClient({ endpoint: "http://127.0.0.1:8141/mcp" });
const context = await client.preflightContext({ query: "structure X regulation" });

console.log(context.items);
```

SDK source lives in [`packages/solomon-ts/`](../../packages/solomon-ts/).
