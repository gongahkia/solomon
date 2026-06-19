# Gemini Provider

The Gemini provider is opt-in per AI command. Shisa never uses it from the prompt-rendering hot path.

Configure:

```sh
export GEMINI_API_KEY=...
```

Optional test or proxy override:

```sh
export SHISA_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Use:

```sh
shisa ai explain --provider gemini --command 'tar -xf app.tar'
shisa ai nextcmd --provider gemini --shell zsh --cwd "$PWD" --last-command 'zig build test' --last-exit 1
shisa ai nl2cmd --provider gemini --shell zsh --cwd "$PWD" --input '?? list large files'
shisa ai risk --provider gemini --slm --command 'kubectl delete pod x'
```

Shisa calls the Gemini GenerateContent API at `POST /v1beta/models/{model}:generateContent?key=$GEMINI_API_KEY` with `contents[].parts[].text`, `role:user`, and `store:false`. The default Gemini model is `gemini-3.5-flash`; pass `--model <name>` to override it.

Before sending input, Shisa applies built-in redaction plus local literal rules from `ai-redact.rules` when available. Cloud request audit entries are appended to `~/.local/state/shisa/ai_cloud.jsonl` with provider id, model id, request SHA-256, redaction-profile SHA-256, status, purpose, and latency bucket. Raw prompt text is not written to that audit log.

Sources: [GenerateContent API](https://ai.google.dev/api/generate-content), [Gemini models](https://ai.google.dev/gemini-api/docs/models), [AI Privacy](ai-privacy.md).
