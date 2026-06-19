# RFC-0003 Internals: Lua Plugin Capability Manifest

RFC: [Lua Plugin Capability Manifest](../../rfcs/0003-lua-plugin-capability-manifest.md)

## Decision

Lua plugins declare identity, exported modules, entry points, and capabilities in `plugin.lua`. Shisa validates the manifest before install/load and checks capabilities at host API boundaries.

## Why

Plugins can expose local state. A manifest gives users, reviewers, and the daemon a compact contract for filesystem, watch, exec, network, env, secrets, and pre-exec access.

## Implementation Notes

- Manifest parsing and validation live under `src/plugin/`.
- Strict install rejects unknown manifest and capability fields.
- Capability grants are exact allow-lists where possible.
- Trusted network grants are provider-scoped, so `net=openai` does not imply `net=anthropic`.
- Lua host APIs must fail closed when the manifest lacks the matching capability.
