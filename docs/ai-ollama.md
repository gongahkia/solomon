# Ollama Integration

`shisa.ai` detects a local Ollama install with `ollama --version`.

Daemon detection checks the local API at `http://127.0.0.1:11434/api/tags`.

Ollama's local API is documented at <https://docs.ollama.com/api/introduction>, and `/api/tags` is documented at <https://docs.ollama.com/api/tags>.
