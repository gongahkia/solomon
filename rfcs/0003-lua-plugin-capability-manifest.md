# RFC-0003: Lua Plugin Capability Manifest

- Status: Accepted
- Created: 2026-06-15
- Owner: core maintainers
- Area: plugin API

## Summary

Every Lua plugin ships a `plugin.lua` manifest that declares identity, supported API version, exported modules, and requested capabilities. The daemon validates the manifest before loading code and enforces declared capabilities at every host API boundary.

## Motivation

Prompt plugins can expose sensitive local state. A manifest gives users and reviewers a compact contract for what a plugin can read, watch, execute, or send over the network.

## Design

Minimal manifest:

```lua
return {
  name = "kubectl-context",
  version = "0.2.1",
  api_version = "1",
  description = "kube context and namespace segment",
  author = "alice <alice@example.com>",
  license = "MIT",
  capabilities = {
    fs_read = { "~/.kube/config" },
    fs_watch = { "~/.kube/config" },
    exec = false,
    net = false,
    secrets = false,
    env_read = { "KUBECONFIG" },
    pre_exec = false,
  },
  modules = { "k8s_ctx" },
}
```

Required fields:

- `name`: lowercase plugin id, `[a-z0-9][a-z0-9._-]*`
- `version`: semver
- `api_version`: supported Shisa plugin API major
- `license`: SPDX identifier
- `capabilities`: table matching this RFC
- `modules`: non-empty list of exported module ids

Recommended fields:

- `description`
- `author`
- `homepage`
- `repository`

Capability fields:

- `fs_read`: list of readable paths or globs
- `fs_watch`: list of watched paths or globs
- `exec`: `false` or list of allowed commands
- `net`: `false` or list of allowed provider/domain ids
- `secrets`: boolean, default `false`
- `env_read`: list of readable environment variable names
- `pre_exec`: boolean, default `false`

All omitted capabilities default to denial.

## Validation

The daemon rejects a plugin when:

- required fields are missing
- names are invalid
- semver is invalid
- `api_version` is unsupported
- capability entries are malformed
- a path escapes allowed user scope without explicit trust
- module ids are duplicated

Capability expansion is deterministic. `~` resolves to the loading user's home directory. Relative paths resolve under the plugin directory and cannot escape it.

## Enforcement

The manifest is not advisory. Host APIs check capabilities before every operation:

- `ctx:read(path)` requires matching `fs_read`
- watcher registration requires matching `fs_watch`
- `ctx:exec(cmd, args)` requires matching `exec`
- network providers require matching `net`
- secret access requires `secrets = true`
- `ctx:env(name)` requires matching `env_read`
- `pre_exec` hooks require `pre_exec = true`

Runtime violations fail the plugin call and are logged as `E_CAPABILITY_DENIED`.

## Performance

Manifest validation happens on load/reload, not on the prompt hot path. Runtime capability checks use precompiled normalized matchers.

## Security

Capability increases across plugin upgrades require renewed user trust. Plugins with `net` or `secrets` capability are never trusted by default.

## Compatibility

The daemon supports the last two plugin API majors after v1. Additive capability fields default to denial so older manifests remain safe.

## Rejected Alternatives

- Implicit trust by install source: too weak for local secrets.
- TOML manifest plus Lua code: easier to parse, but splits plugin metadata from Lua plugin distribution.
- Broad boolean capabilities only: not granular enough for filesystem and command safety.

## Unresolved Questions

- Exact glob syntax for cross-platform path matching.
- Whether future publisher-identity signatures should bind to normalized manifest bytes or the full plugin bundle.
