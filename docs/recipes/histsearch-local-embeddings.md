# Local Semantic History Search with Ollama Embeddings

This recipe is the local-model path for a future `histsearch` pack. It keeps shell history, embeddings, and search queries on the machine.

## 1. Pull the embedding model

Use Ollama's embedding endpoint with `nomic-embed-text`.

```sh
ollama serve
ollama pull nomic-embed-text
```

Smoke-test the endpoint:

```sh
curl http://localhost:11434/api/embed \
  -d '{"model":"nomic-embed-text","input":"search_document: git status --short"}'
```

Expected shape:

```json
{
  "model": "nomic-embed-text",
  "embeddings": [[0.01, -0.02]]
}
```

## 2. Normalize history records

Store command records before embedding. Keep raw shell history private and avoid indexing obvious secrets.

```text
id: stable hash of shell + timestamp + command
shell: zsh | bash | fish | nu | pwsh
cwd: working directory when known
exit: last exit code when known
command: normalized command text
redacted_command: built-in redaction + local ai-redact.rules
```

Embedding input should be short and stable:

```text
search_document: cwd=/repo exit=0 cmd=git status --short
```

For queries:

```text
search_query: how did I check dirty git files?
```

## 3. Store vectors locally

Preferred first implementation:

- SQLite table for command metadata.
- SQLite vector extension (`sqlite-vss` or `sqlite-vec`) for embeddings.
- One vector row per command record.
- No daemon prompt-path dependency; index in a background command or explicit `shisa histsearch index`.

Minimal schema:

```sql
CREATE TABLE history_item (
  id TEXT PRIMARY KEY,
  shell TEXT NOT NULL,
  cwd TEXT NOT NULL,
  exit_code INTEGER NOT NULL,
  command TEXT NOT NULL,
  redacted_command TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE history_embedding USING vss0(
  embedding(768)
);
```

Keep the database under:

```text
$XDG_DATA_HOME/shisa/history-embeddings.sqlite
```

Fallback:

```text
~/.local/share/shisa/history-embeddings.sqlite
```

## 4. Query flow

The query flow should stay explicit, not prompt-driven.

```text
read query
redact query
embed "search_query: <query>"
vector search top K
join metadata rows
print command, cwd, exit, age
```

Suggested CLI shape:

```sh
shisa histsearch index --history "${HISTFILE:-}"
shisa histsearch query "git dirty files"
```

## 5. Native path later

If the project avoids the Ollama daemon later, use a native embedding backend behind the same interface:

```text
embed(model_id, input) -> []f32
```

Candidate backends:

- `llama.cpp` embedding mode with a local GGUF embedding model.
- Candle-based embedding runner if the build accepts a Rust sidecar.

Keep backend choice out of the prompt render path.
