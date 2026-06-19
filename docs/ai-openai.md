# OpenAI Provider

The OpenAI provider is opt-in per AI command. Shisa never uses it from the prompt-rendering hot path.

Configure:

```sh
export OPENAI_API_KEY=...
```

Optional test or proxy override:

```sh
export SHISA_OPENAI_BASE_URL=https://api.openai.com/v1/responses
```

Use:

```sh
shisa ai explain --provider openai --command 'tar -xf app.tar'
shisa ai nextcmd --provider openai --shell zsh --cwd "$PWD" --last-command 'zig build test' --last-exit 1
shisa ai nl2cmd --provider openai --shell zsh --cwd "$PWD" --input '?? list large files'
shisa ai risk --provider openai --slm --command 'kubectl delete pod x'
```

Shisa calls the OpenAI Responses API at `POST /v1/responses` with `model`, redacted `input`, and `store:false`. The default OpenAI model is `gpt-5.5`; pass `--model <name>` to override it.

Before sending input, Shisa applies built-in redaction plus local literal rules from `ai-redact.rules` when available. Cloud request audit entries are appended to `~/.local/state/shisa/ai_cloud.jsonl` with provider id, model id, request SHA-256, redaction-profile SHA-256, status, purpose, and latency bucket. Raw prompt text is not written to that audit log.

Sources: [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), [latest model guidance](https://developers.openai.com/api/docs/guides/latest-model.md), [AI Privacy](ai-privacy.md).
