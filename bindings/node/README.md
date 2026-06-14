# Node Bindings

Node.js package and `napi-rs` bindings for Shibahama.

```bash
npm install
npm run build
npm test
```

```js
import { LangChainMemory, Shibahama } from "shibahama";

const engine = new Shibahama("memory.redb", 2);
const memory = new LangChainMemory(engine, {
  embed: async (text) => [Number(text.includes("user")), Number(text.includes("task"))],
});

await memory.saveContext({ input: "remember short replies" }, { output: "stored" });
const variables = await memory.loadMemoryVariables({ input: "short replies" });
```

The Node wrapper exposes the practical core operations: write, recall, timeline,
reinforce, `why`, event/audit drill-down, consolidation, challenge, affirm,
correct, pin, and unpin. Native `*Json()` methods return JSON strings; the
JavaScript wrapper adds parsed-object helpers such as `eventRecords()`,
`audit()`, and `consolidate()`.

`LangChainMemory.clear()` is a compatibility-only no-op. It does not delete or
invalidate durable Shibahama memories; use separate stores or namespaces when a
caller needs isolated context.
