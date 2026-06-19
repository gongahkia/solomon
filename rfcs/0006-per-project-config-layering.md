# RFC-0006: Per-Project Config Layering

- Status: Draft
- Created: 2026-06-19
- Owner: core maintainers
- Area: config

## Summary

Shisa should support project-local config files that layer over the user config without letting a repository silently expand trust, run commands, enable networked AI providers, or change plugin capabilities.

## Motivation

Teams often want a shared prompt shape for one repo: VCS modules, cloud-risk wording, IaC workspace hints, or right-prompt layout. Today the user must copy those choices into their global `shisa.toml`, which makes repo-specific safety context hard to share and easy to forget.

The risk is that config files inside cloned repositories are untrusted input. A project config must be useful for prompt layout while staying unable to escalate host access.

## Design

### File Discovery

When project layering is enabled, the daemon resolves config in this order:

1. built-in defaults
2. user config at `$XDG_CONFIG_HOME/shisa/shisa.toml` or `~/.config/shisa/shisa.toml`
3. ancestor project configs named `.shisa.toml`, from repository root toward the current directory
4. nearest-directory overrides last

Discovery starts at the render `cwd`, walks upward, and stops at the first of:

- filesystem root
- user home directory
- VCS root parent
- mount boundary when detectable

The daemon must expose the resolved layer list through `shisa explain` so users can see which files affected the prompt.

### Merge Rules

Layering uses explicit table merge rules:

| Field kind | Merge rule |
| --- | --- |
| scalar top-level keys | nearest layer wins |
| `[prompt].modules` and `[prompt].right_modules` | nearest layer replaces the array |
| per-module option tables | shallow merge by key |
| `[ai]` | user config wins unless the project layer is trusted |
| theme path | project layers may select built-in theme ids only unless trusted |

Unknown keys remain invalid. Duplicate module ids remain invalid after the final merge.

### Trust Boundary

Project configs are untrusted by default. Untrusted layers may set:

- prompt module order
- right-prompt module order
- safe per-module display options
- built-in theme id
- `rtl_reverse`

Untrusted layers may not set:

- plugin trust
- plugin enable/disable state
- plugin capabilities
- AI cloud provider, model, or plugin id
- external command allow-lists
- absolute or tilde theme paths
- future shell hook behavior

Trusted project config is a separate user action:

```sh
shisa config trust-project /path/to/repo
```

The trust record stores the canonical repo root and a digest of trusted `.shisa.toml` files. Changing a trusted project config invalidates trust until the user re-confirms.

### Cache And Invalidation

The daemon caches resolved config by `cwd` plus the ordered list of layer paths and mtimes. Each discovered `.shisa.toml` becomes an fsnotify watch. When a layer changes:

1. invalidate affected resolved-config entries
2. bump config generation
3. force a fresh parse on the next render
4. include the changed layer path in `shisa doctor` diagnostics when parsing fails

Config discovery must not run on the shell hot path. The daemon can return the last valid resolved config while an async refresh is pending, but it must surface a diagnostic when the latest project config failed validation.

## Performance

Warm render still targets p99 under 2 ms. Directory walking and config parsing must be daemon-owned and cached. The benchmark plan must include:

- no project config
- one repository-root `.shisa.toml`
- nested `.shisa.toml` files
- invalid nearest config with fallback to the last valid layer set

## Security

Repository-controlled config is attacker-controlled input. The first implementation must fail closed:

- no command execution from project config
- no network provider enablement from project config
- no plugin capability expansion from project config
- no absolute theme path from untrusted project config
- no symlink escape outside the canonical discovered layer path

Trust records must be scoped to canonical repository roots, not display paths.

## Compatibility

Existing global-only configs keep the same behavior when no `.shisa.toml` is discovered or when project layering is disabled.

Project config parse errors must not prevent rendering with the last valid global config. They should appear in `shisa doctor`, `shisa explain`, and daemon diagnostics.

## Rejected Alternatives

- Always trust project config: unsafe for cloned repositories.
- Only read the nearest `.shisa.toml`: loses useful repo-root defaults.
- Deep merge every table recursively: hard to explain and easy to make precedence ambiguous.
- Store trust by path only: misses config changes after trust.

## Unresolved Questions

- Whether project layering is enabled by default after v1 or requires an opt-in flag.
- Whether trust should include file digests only or also Git commit ids when available.
- Whether project configs may use a future `extends` key.
- How much of `[ai]` can be safely project-scoped for local-only providers.
