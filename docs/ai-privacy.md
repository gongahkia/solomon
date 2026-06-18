# AI Privacy

Shisa AI features are opt-in. The default supported path is local Ollama on `127.0.0.1:11434`.

## Contract

- Core prompt rendering must not make network calls.
- Local model features may send prompts to a local model daemon only after the user invokes an AI command.
- Cloud providers must be implemented as plugins or providers with an explicit `net` capability.
- Provider trust must be per provider, not global.
- Secrets, tokens, SSH config, kubeconfig data, cloud account ids, and command history must be redacted before cloud requests.
- Audit logs for cloud requests must store hashes and metadata by default, not raw prompt text.

## Local Data

Local AI commands may read:

- current working directory
- last command and exit code when passed by the caller
- shell name
- model name
- local history paths only when the command explicitly asks for history context

Local AI commands must fail closed when the model daemon is unavailable.

## Cloud Data

Cloud provider support is not part of the default prompt path. A cloud provider must document:

- provider id
- network endpoint
- fields sent
- redaction rules
- audit-log fields
- retention assumptions

## Default Redaction Rules

Default redaction replaces matched values with `[redacted]`. The built-in rules cover key/value fields named `password`, `token`, `secret`, `api_key`, AWS credential names, kubeconfig key data, and SSH `IdentityFile`; bearer tokens; AWS access keys; GitHub `gh*_` tokens; `sk-` provider keys; PEM private-key blocks; and 12-digit cloud account ids.

Local literal rules are stored in the config-dir `ai-redact.rules` file by default. Blank lines and `#` comments are ignored. Use `shisa ai redact --add-literal <text>` to append a rule, `shisa ai redact --test <text>` to preview built-in plus local redaction, and `--rules <path>` to test an alternate file.

## Audit Fields

Cloud request audit entries should include:

- timestamp
- provider id
- model id
- request hash
- redaction profile hash
- success or failure class
- latency bucket

Raw command text and raw model prompts are excluded by default.
