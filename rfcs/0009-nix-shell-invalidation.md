# RFC-0009: nix-shell PATH Cache Invalidation

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: cache, daemon lifecycle

## Summary

`language_versions` must stop reusing toolchain output across abrupt PATH changes from `nix-shell`, `devenv shell`, and `flox activate`.

The v1 implementation is opt-in:

```toml
[modules.language_versions]
path_hash_invalidate = true
```

When enabled, the shell client sends:

- `env_hash`: SHA-256 of the active `$PATH`
- `path_env`: the active `$PATH`, only for local language-version probes

The daemon keys the language-version cache by `(cwd, env_hash)` and runs probe commands with `path_env` as `PATH`.

## Problem

The daemon can outlive a development shell. A user may start Shisa in an outer shell, enter `nix-shell -p python311`, and keep the same daemon. Without a PATH-sensitive cache key, `language_versions` can reuse the outer result, for example `python 3.10`, even though the active shell resolves `python3` to Python 3.11.

Reproduction shape:

```sh
python3 --version
shisa prompt
nix-shell -p python311 --run 'python3 --version && shisa prompt'
```

Expected: the second prompt reflects the `nix-shell` Python. Failure mode: the prompt keeps the outer version until another invalidation happens.

The same pattern applies to:

- `devenv shell` when package or language options expose a different interpreter
- `flox activate` when activation prepends environment package bins to PATH
- in-place activation through shell hooks where the daemon process environment does not change

## Sources

- Nix reference manual: `nix-shell` starts an interactive shell with derivation environment variables set and setup sourced. https://nix.dev/manual/nix/2.18/command-ref/nix-shell
- devenv ad-hoc environments can create language/package shells from command-line options. https://devenv.sh/ad-hoc-developer-environments/
- Flox activation makes packages and environment variables available and can place environment bins at the front of PATH. https://flox.dev/docs/concepts/activation

## Alternatives

### 1. PATH Hash on Every Render

Compute SHA-256 over `$PATH` in the client and send it as `env_hash`.

Pros:

- cheap fixed-size request field
- no filesystem watcher fan-out
- directly matches the active shell state
- invalidates on every PATH flip, including nested shells

Cons:

- hash alone is not enough for a persistent daemon to execute the right interpreter
- requires request payload/schema change

### 2. Watch `/nix/store/*` or Profile Dirs

Subscribe to filesystem events under Nix store paths, profiles, and environment metadata.

Pros:

- daemon-only implementation
- can catch profile rebuilds without a render

Cons:

- `/nix/store` is huge and mostly unrelated to the current prompt
- profile changes do not prove the active shell PATH changed
- devenv/flox activation can be shell-local without useful daemon-visible events

### 3. Client Activation Marker

Client passes an `activation_id`, such as `nix-shell:<hash>`, `devenv:<path>`, or `flox:<env>`.

Pros:

- explicit domain signal
- can include stable environment identity beyond PATH
- useful for future diagnostics

Cons:

- shell hook cooperation required per ecosystem
- incomplete for arbitrary PATH-manipulating tools
- still needs PATH for daemon-side command execution

### 4. Combination

Use option 1 by default when opted in, then add option 3 for richer ecosystem UX.

## Recommendation

Adopt option 4:

1. v1: opt-in `path_hash_invalidate = true`.
2. Client sends both `env_hash` and `path_env`.
3. Daemon caches `language_versions` by `(cwd, env_hash)`.
4. Daemon runs language probes with `PATH=path_env`.
5. Later: add `activation_id` as an optional partition key once shell hooks can identify Nix/devenv/flox activation reliably.

This is intentionally scoped to `language_versions`. Other modules should not read `path_env` unless they get their own config gate and RFC.

## Cost

SHA-256 over a normal PATH is microsecond-scale and does not spawn processes. The IPC payload adds one PATH-sized string only when opted in.

Expected render cost delta:

- disabled: zero payload and cache-key change beyond default fields
- enabled warm render: SHA-256 + JSON escaping of PATH
- enabled invalidation: one async language probe miss, same as cwd change

Budget: warm render delta must stay at or below 0.5 ms inside a nix-shell.

Benchmark command:

```sh
bash bench/compare-prompts.sh --scenario nixshell
```

## Config

```toml
[modules.language_versions]
detect = ["python", "node", "rust", "go"]
path_hash_invalidate = true
```

Defaults:

- `path_hash_invalidate = false`
- older configs preserve current behavior
- older daemons ignore unknown request fields per protocol v1

## Protocol

Render requests gain two optional fields:

```json
{
  "env_hash": "64 lowercase hex chars",
  "path_env": "/nix/store/.../bin:/usr/bin"
}
```

`env_hash` is cache identity. `path_env` is command execution input. The daemon must not log or persist `path_env`.

## Security

PATH can expose user directory names and environment manager layout. Therefore:

- default off in v1
- sent only when `path_hash_invalidate = true`
- not included in rendered prompt cache keys
- not logged in metrics or diagnostics
- used only as `PATH` for local language-version child processes

The daemon still resolves commands by normal executable lookup. It does not execute shell text from `path_env`.

## Tests

- Unit: language cache invalidates when `env_hash` changes.
- Unit: language probe resolves `python3` from request `path_env`.
- Integration: `test/integration/nix_shell_language_version.sh` enters `nix-shell -p python311` when available and rejects stale outer Python output.

## Non-Goals

- Guix support.
- direnv-specific activation semantics.
- General environment snapshot transport.
- Watching `/nix/store`.
