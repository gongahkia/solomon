# Ollama Integration

`shisa.ai` detects a local Ollama install with `ollama --version`.

Daemon detection checks the local API at `http://127.0.0.1:11434/api/tags`.

The default recommended model is `gemma3:1b`, selected as the smallest current candidate in the Phase 12 shortlist.

The client supports:

- `GET /api/tags` for daemon health.
- `POST /api/pull` with `{"stream": false}` for non-streaming pulls.
- `POST /api/generate` with `{"stream": false}` for deterministic single-response calls.
- `POST /api/generate` with `{"stream": true}` for NDJSON token streaming. Cancellation is checked between streamed chunks.

`shisa ai bench` reports cold first-token latency after unloading the selected model, warm first-token latency after preloading it, token throughput from Ollama's final `eval_count` / `eval_duration` metrics, and a memory ceiling from `/api/ps`.

```sh
shisa ai bench --model gemma3:1b --prompt "Reply with ok."
shisa ai bench --cold
shisa ai bench --warm
shisa ai bench --memory
shisa ai bench --all-supported --memory
```

`shisa ai status` reports local Ollama install/running state, the recommended local model, configured cloud-provider state, and local audit-log paths.

Deterministic tests use `ollama.mockModelListener` and `ollama.serveOneMockGenerate` to serve a local one-request `/api/generate` response without requiring Ollama or a downloaded model.

Prompt regression snapshots live in `test/fixtures/ai/prompt-regression.json` and are exercised by `src/ai/regression.zig` during `zig build test`.

Ollama's local API is documented at <https://docs.ollama.com/api/introduction>. `/api/tags`, `/api/pull`, and `/api/generate` are documented at <https://docs.ollama.com/api/tags>, <https://docs.ollama.com/api/pull>, and <https://docs.ollama.com/api/generate>.

Opt-in cloud providers are documented in [OpenAI Provider](ai-openai.md), [Anthropic Provider](ai-anthropic.md), and [Gemini Provider](ai-gemini.md). Privacy rules live in [AI Privacy](ai-privacy.md).
