# Ollama Integration

`shisa.ai` detects a local Ollama install with `ollama --version`.

Daemon detection checks the local API at `http://127.0.0.1:11434/api/tags`.

The default recommended model is `gemma3:1b`, selected as the smallest current candidate in the Phase 12 shortlist.

The client supports:

- `GET /api/tags` for daemon health.
- `POST /api/pull` with `{"stream": false}` for non-streaming pulls.
- `POST /api/generate` with `{"stream": false}` for deterministic single-response calls.
- `POST /api/generate` with `{"stream": true}` for NDJSON token streaming. Cancellation is checked between streamed chunks.

Ollama's local API is documented at <https://docs.ollama.com/api/introduction>. `/api/tags`, `/api/pull`, and `/api/generate` are documented at <https://docs.ollama.com/api/tags>, <https://docs.ollama.com/api/pull>, and <https://docs.ollama.com/api/generate>.
