# AI Privacy

Shisa AI features are opt-in. The default supported path is local Ollama on `127.0.0.1:11434`.

## Contract

- Core prompt rendering must not make network calls.
- Local model features may send prompts to a local model daemon only after the user invokes an AI command.
- Cloud providers must be implemented as plugins or providers with an explicit `net` capability.
- Provider trust must be per provider, not global.
- Secrets, tokens, SSH config, kubeconfig data, cloud account ids, and command history must be redacted before cloud requests.
- Audit logs for cloud requests must store hashes and metadata by default, not raw prompt text.

Provider-scoped trust uses `shisa plugin trust <name> --net=<provider>`. A trust grant for one provider does not cover another provider or non-network capabilities.

## Local Data

Local AI commands may read:

- current working directory
- last command and exit code when passed by the caller
- stderr text only when a caller explicitly passes it to the local errfix rule engine
- shell name
- model name
- local history paths only when the command explicitly asks for history context

Local AI commands must fail closed when the model daemon is unavailable.

The errfix rule engine is deterministic and local-only. It matches curated stderr patterns before any model-backed suggestion path exists.

The built-in LM Studio provider uses provider id `lmstudio`, endpoint `POST http://127.0.0.1:1234/v1/responses` by default, `model`, and raw `input`. Its base URL must remain loopback (`127.0.0.1`, `localhost`, or `[::1]`).

The built-in llama.cpp provider uses provider id `llamacpp`, runs `llama-cli` directly, and sends raw `input` through a temporary 0600 prompt file rather than argv. It requires `SHISA_LLAMA_CPP_MODEL` or `--model /path/to/model.gguf`.

## Cloud Data

Cloud provider support is not part of the default prompt path. A cloud provider must document:

- provider id
- network endpoint
- fields sent
- redaction rules
- audit-log fields
- retention assumptions

The built-in OpenAI provider uses provider id `openai`, endpoint `POST https://api.openai.com/v1/responses`, `Authorization: Bearer $OPENAI_API_KEY`, `model`, redacted `input`, and `store:false`. It is selected per command with `--provider openai`.

The built-in Anthropic provider uses provider id `anthropic`, endpoint `POST https://api.anthropic.com/v1/messages`, `x-api-key: $ANTHROPIC_API_KEY`, `anthropic-version: 2023-06-01`, `model`, `max_tokens`, and one redacted user message. It is selected per command with `--provider anthropic`.

The built-in Gemini provider uses provider id `gemini`, endpoint `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=$GEMINI_API_KEY`, `contents[].parts[].text`, `role:user`, and `store:false`. It is selected per command with `--provider gemini`.

When `[ai].provider` selects `openai`, `anthropic`, or `gemini`, `[ai].plugin` must name a trusted plugin and that plugin must have a matching `net=<provider>` grant. Explicit CLI `--provider` still requires the provider API key but does not inherit `[ai].plugin`.

## Default Redaction Rules

Default redaction replaces matched values with `[redacted]`. The built-in rules cover key/value fields named `password`, `token`, `secret`, `api_key`, AWS credential names, kubeconfig key data, and SSH `IdentityFile`; bearer tokens; AWS access keys; GitHub `gh*_` tokens; `sk-` provider keys; PEM private-key blocks; and 12-digit cloud account ids.

Local literal rules are stored in the config-dir `ai-redact.rules` file by default. Blank lines and `#` comments are ignored. Use `shisa ai redact --add-literal <text>` to append a rule, `shisa ai redact --test <text>` to preview built-in plus local redaction, and `--rules <path>` to test an alternate file.

## Audit Fields

Pre-exec cloud request audit entries in `~/.local/state/shisa/cloud_requests.jsonl` include:

- timestamp
- request kind
- shell
- cwd SHA-256 hash
- command SHA-256 hash
- force flag

Provider-backed AI request audit entries in `~/.local/state/shisa/ai_cloud.jsonl` include provider id, model id, request SHA-256 hash, redaction profile SHA-256 hash, success or failure class, purpose, and latency bucket.

Raw command text, raw cwd, and raw model prompts are excluded by default.
