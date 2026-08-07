# RFC-0010: Local AI Plugin Capability

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: AI, plugin security

## Summary

Shisa core remains AI-free. This RFC evaluates whether a future opt-in plugin capability may allow local model hints through a user-declared localhost model endpoint, without adding AI code to the daemon, shell hot path, or default install.

The recommendation is to keep AI banned from core, allow no first-class AI module, and prototype only a dedicated `ai_local` plugin capability after a third-party plugin proves demand. General `network` plus `exec` is too broad for model access; cloud AI remains out of scope for this RFC.

## Motivation

The current ban is intentional. North-star section 3 says Shisa is not an AI coding agent and that the daemon and core binary contain no AI code. Section 18 sketches a future opt-in `shisa.ai` pack, but that section is explicitly outside the core contract.

Two phase-0 commits removed the old AI surface:

- `f1bf59b` removed `src/ai/*` providers and AI command implementations from the core tree.
- `2059380` removed AI docs, prompts, i18n strings, and AI config keys.

That history closed a real scope problem: AI code was present before the prompt daemon, plugin sandbox, and capability boundaries were mature. Reopening the topic requires a narrower design that preserves the hot-path and privacy contracts.

## Design Space

### Alternative 1: Keep AI Fully Banned

Core and official plugins expose no AI capability. Users may still build private plugins, but Shisa does not add host APIs that make model access easier.

Pros:

- strongest privacy story
- no new prompt-injection surface
- no latency risk
- no extra review burden

Cons:

- leaves local-model use cases outside the supported plugin model
- pushes users toward ad hoc shell scripts with weaker capability review
- makes section 18 permanently aspirational

### Alternative 2: General Plugin Capability

AI plugins use existing capabilities: `net` for HTTP to a model server and `exec` for `ollama`, `llama.cpp`, or `mlx` subprocesses.

Pros:

- no new capability type
- matches existing manifest machinery
- permits non-AI local services too

Cons:

- too broad: `net=localhost` can reach unrelated local admin panels
- `exec=ollama` still allows model lifecycle side effects
- review cannot distinguish "local model hint" from general network or subprocess power

### Alternative 3: Dedicated `ai_local` Capability

Add a narrow plugin capability:

```lua
capabilities = {
  ai_local = {
    endpoint = "http://127.0.0.1:11434",
    model = "qwen2.5:1.5b",
    max_prompt_bytes = 8192,
    max_requests_per_minute = 20,
  },
}
```

Rules:

- endpoint must resolve to loopback (`127.0.0.1` or `::1`)
- no outbound network destinations
- no model subprocess management
- no hot-path calls; only async, pre-exec, or explicit user command surfaces
- no shell history access unless a separate future `shell_history` capability exists
- request/response metadata logged locally with redacted payload hashes, not raw text

Pros:

- reviewable user prompt: "this plugin may call local model X at localhost Y"
- narrower than general `net`
- keeps cloud providers outside this RFC
- preserves no-AI-in-core: the daemon enforces a capability, not model logic

Cons:

- new capability and docs surface
- still creates prompt-injection and data-minimization work
- localhost services are not always private on shared machines or forwarded ports

### Alternative 4: First-Class Core Module

Add built-in AI modules to core, similar to the removed `src/ai/*` implementation.

Pros:

- best UX if Shisa wanted AI as a headline feature
- easiest to benchmark and document centrally

Cons:

- directly violates north-star section 3
- recreates the removed phase-0 scope problem
- forces every install to carry AI review and supply-chain risk
- makes hot-path isolation harder to prove

## Threat Model

### Prompt Injection

Inputs such as recent commands, cwd names, Git branch names, filenames, and stderr are attacker-controlled in many repos. A model prompt can be induced to suggest dangerous commands or reveal local context. Any AI plugin must treat model output as untrusted text and must never auto-run commands.

### Exfiltration

Prompt context can contain secrets: cloud profile names, repo paths, branch names, command arguments, and error output. `ai_local` must only allow loopback endpoints and must not permit cloud providers. If a user tunnels localhost or runs a remote devcontainer, the plugin UI must still describe the effective endpoint.

### Latency Injection

Model calls can take hundreds of milliseconds or seconds. They must not occur during `render`. Acceptable surfaces are explicit commands, async hints that can be dropped, or pre-exec gates with clear UI and timeout.

### Capability Confusion

`net` and `exec` are general powers. If local model access is permitted through them, users cannot tell whether a plugin is narrowly making AI hints or broadly reaching local services. A dedicated capability reduces this ambiguity.

### Local Audit

No raw prompts are logged by default. The plugin host may log timestamp, plugin id, endpoint, model id, redacted payload hash, byte counts, and latency. Users can opt into raw local debug logs when diagnosing a plugin.

## Recommendation

Adopt Alternative 3 only after the plugin runtime has at least one external consumer and the `ai_local` capability has a focused prototype. Until then, Alternative 1 remains the active policy.

The first prototype should be an external plugin, not core. It should implement one low-risk command such as `shisa.ai explain-selected-command` or `cdhint`, with these constraints:

- local endpoint only
- no shell history capture
- no prompt render calls
- hard timeout
- payload byte cap
- local audit metadata
- explicit trust prompt describing endpoint and model

Cloud AI providers require a separate RFC because they cross the zero-telemetry and exfiltration boundary differently from localhost.

## Compatibility

This is additive to the plugin manifest. Omitted `ai_local` defaults to denial. Older daemons reject or ignore unknown manifest fields according to the plugin API version rules; therefore the capability requires a plugin API minor or major decision before implementation.

No code changes are authorized by this Draft. It records the decision space and a possible future shape.

## Performance

Core render p99 must remain unchanged because no AI work runs in `render`. The capability check is manifest-time plus host API boundary validation. Any accepted implementation must prove:

- zero model calls during `render`
- no extra client request fields on the default prompt path
- no material regression in a recorded `scripts/perf-suite.sh --repo ...` run

## Security

The daemon must fail closed:

- non-loopback endpoint: deny
- missing `ai_local`: deny
- request over byte cap: deny
- hot-path call attempt: deny
- missing audit metadata sink: deny or disable AI call, depending on accepted implementation

The trust prompt must name the endpoint, model, byte cap, and whether any other capabilities are requested.

## Rejected Alternatives

- Cloud AI under `net`: too easy to violate the zero-telemetry contract by accident.
- `exec`-managed model servers: too much host mutation for a prompt plugin capability.
- First-class core AI module: contradicts the current north-star and repeats the removed implementation.

## Unresolved Questions

- Whether `ai_local` belongs in plugin API v1 as an additive field or requires v2.
- Whether localhost inside SSH, containers, and WSL needs extra endpoint wording.
- Whether local audit metadata should be daemon-owned or plugin-owned.
- Whether command history access needs a separate capability and RFC.
