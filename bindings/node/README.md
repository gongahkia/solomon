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
