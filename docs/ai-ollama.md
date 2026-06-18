# Ollama Integration

`shisa.ai` detects a local Ollama install with `ollama --version`.

Daemon detection checks the local API at `http://127.0.0.1:11434/api/tags`.

The default recommended model is `gemma3:1b`, selected as the smallest current candidate in the Phase 12 shortlist.

The client supports:

- `GET /api/tags` for daemon health.
- `POST /api/pull` with `{"stream": false}` for non-streaming pulls.
- `POST /api/generate` with `{"stream": false}` for deterministic single-response calls.
- `POST /api/generate` with `{"stream": true}` for NDJSON token streaming. Cancellation is checked between streamed chunks.

`shisa ai bench` reports first-token latency, token throughput from Ollama's final `eval_count` / `eval_duration` metrics, and loaded model size from `/api/ps`.

`shisa ai status` reports local Ollama install/running state, the recommended local model, configured cloud-provider state, and local audit-log paths.

Deterministic tests use `ollama.mockModelListener` and `ollama.serveOneMockGenerate` to serve a local one-request `/api/generate` response without requiring Ollama or a downloaded model.

Ollama's local API is documented at <https://docs.ollama.com/api/introduction>. `/api/tags`, `/api/pull`, and `/api/generate` are documented at <https://docs.ollama.com/api/tags>, <https://docs.ollama.com/api/pull>, and <https://docs.ollama.com/api/generate>.

Privacy rules live in [AI Privacy](ai-privacy.md).
