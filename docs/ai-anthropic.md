# Anthropic Provider

The Anthropic provider is opt-in per AI command. Shisa never uses it from the prompt-rendering hot path.

Configure:

```sh
export ANTHROPIC_API_KEY=...
```

Optional test or proxy override:

```sh
export SHISA_ANTHROPIC_BASE_URL=https://api.anthropic.com/v1/messages
```

Use:

```sh
shisa ai explain --provider anthropic --command 'tar -xf app.tar'
shisa ai nextcmd --provider anthropic --shell zsh --cwd "$PWD" --last-command 'zig build test' --last-exit 1
shisa ai nl2cmd --provider anthropic --shell zsh --cwd "$PWD" --input '?? list large files'
shisa ai risk --provider anthropic --slm --command 'kubectl delete pod x'
```

Shisa calls the Anthropic Messages API at `POST /v1/messages` with `model`, `max_tokens`, and one redacted user message. It sends `x-api-key` and `anthropic-version: 2023-06-01`. The default Anthropic model is `claude-fable-5`; pass `--model <name>` to override it.

Before sending input, Shisa applies built-in redaction plus local literal rules from `ai-redact.rules` when available. Cloud request audit entries are appended to `~/.local/state/shisa/ai_cloud.jsonl` with provider id, model id, request SHA-256, redaction-profile SHA-256, status, purpose, and latency bucket. Raw prompt text is not written to that audit log.

Source: [Anthropic Messages API](https://docs.anthropic.com/en/api/messages), [AI Privacy](ai-privacy.md).
