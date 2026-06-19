# llama.cpp Provider

The llama.cpp provider is opt-in per AI command. Shisa never uses it from the prompt-rendering hot path.

Configure:

```sh
export SHISA_LLAMA_CPP_MODEL=/path/to/model.gguf
```

Optional binary override:

```sh
export SHISA_LLAMA_CPP_BIN=llama-cli
```

Use:

```sh
shisa ai explain --provider llamacpp --command 'tar -xf app.tar'
shisa ai nextcmd --provider llamacpp --shell zsh --cwd "$PWD" --last-command 'zig build test' --last-exit 1
shisa ai nl2cmd --provider llamacpp --shell zsh --cwd "$PWD" --input '?? list large files'
shisa ai risk --provider llamacpp --slm --command 'kubectl delete pod x'
```

You can also pass a model path directly:

```sh
shisa ai explain --provider llamacpp --model /path/to/model.gguf --command 'tar -xf app.tar'
```

Shisa runs `llama-cli` directly with `-m`, `-f`, `-n 512`, `--no-display-prompt`, `--no-show-timings`, `--log-disable`, and `-st`. The prompt is written to a temporary 0600 file and passed with `-f` so prompt text is not placed in argv.

Sources: [llama.cpp llama-cli docs](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/cli/README.md), [AI Privacy](ai-privacy.md).
