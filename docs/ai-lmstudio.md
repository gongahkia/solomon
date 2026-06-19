# LM Studio Provider

The LM Studio provider is opt-in per AI command. Shisa never uses it from the prompt-rendering hot path.

Start the local server:

```sh
lms server start --port 1234
```

Optional local base URL override:

```sh
export SHISA_LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
```

Use:

```sh
shisa ai explain --provider lmstudio --model openai/gpt-oss-20b --command 'tar -xf app.tar'
shisa ai nextcmd --provider lmstudio --model openai/gpt-oss-20b --shell zsh --cwd "$PWD" --last-command 'zig build test' --last-exit 1
shisa ai nl2cmd --provider lmstudio --model openai/gpt-oss-20b --shell zsh --cwd "$PWD" --input '?? list large files'
shisa ai risk --provider lmstudio --model openai/gpt-oss-20b --slm --command 'kubectl delete pod x'
```

Shisa calls LM Studio's OpenAI-compatible Responses API at `POST /v1/responses` with `model` and `input`. The default LM Studio model is `openai/gpt-oss-20b`; pass `--model <name>` for the loaded model identifier in your LM Studio server.

The base URL must be loopback (`127.0.0.1`, `localhost`, or `[::1]`). Shisa does not write LM Studio requests to the cloud-provider audit log because the provider is local-only.

Sources: [LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat), [LM Studio Responses](https://lmstudio.ai/docs/developer/openai-compat/responses), [AI Privacy](ai-privacy.md).
