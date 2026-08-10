# Plugin Manifest

Plugin metadata lives in `plugin.lua` and returns a table matching this schema.

```lua
return {
  name = "kubectl-context",
  version = "0.2.1",
  api_version = 1,
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
  on_load = "on_load",
  render = "render",
  update = "update",
  on_unload = "on_unload",
}
```

Required fields:

- `name`: lowercase id, `[a-z0-9][a-z0-9._-]*`.
- `version`: semver.
- `api_version`: supported Shisa plugin API major, currently `1`.
- `license`: SPDX-like identifier.
- `capabilities`: capability table. Omitted capabilities deny access.
- `modules`: non-empty exported module id list.

Optional fields:

- `on_load`: Lua function name for load-time setup.
- `render`: Lua function name, defaults to `render`.
- `update`: Lua function name for async/cache refresh.
- `pre_exec`: Lua function name. Requires `capabilities.pre_exec = true` before command preflight integration can call it.
- `on_unload`: Lua function name for cleanup.
- `description`
- `author`
- `homepage`
- `repository`

Capabilities:

- `fs_read`: readable paths or globs.
- `fs_watch`: watched paths or globs.
- `exec`: `false` or allowed command names.
- `net`: `false` or allowed provider/domain ids.
- `secrets`: boolean, default `false`.
- `env_read`: readable environment variable names.
- `pre_exec`: boolean, default `false`.

Capability risks and review guidance are documented in `docs/capabilities.md`.

Validation rejects malformed names, unsupported API versions, duplicate modules, invalid entry points, and malformed capability entries.

Capability checks:

- Missing capability fields deny access.
- `fs_read` and `fs_watch` match exact paths or recursive scopes ending in `/**`.
- `~/` resolves against the loading user's home directory.
- Relative filesystem scopes resolve under the plugin directory.
- `exec`, `net`, and `env_read` are exact allow-lists.

Lifecycle contracts and wall-time limits:

| Hook | Max wall time | Contract |
| --- | --- | --- |
| `on_load(ctx)` | 1 ms | Initialize plugin-local state after trust/load. Return value is ignored. |
| `render(ctx)` | 1 ms | Return a prompt segment string, `nil`, or an empty string. It must be bounded and side-effect-light. |
| `update(ctx)` | 1 ms | Refresh plugin cache/state outside the prompt hot path. Return value is plugin-defined. |
| `pre_exec(ctx)` | 1 ms | Inspect a pending command and return `nil` or a decision table such as `{ allow = false, message = "..." }`. Requires `capabilities.pre_exec = true`. |
| `on_unload(ctx)` | 1 ms | Release transient resources before reload, disable, or daemon shutdown. Return value is ignored. |

All lifecycle hooks share the current Lua runtime budget: 1 ms per call. Debug builds use a 5 ms hard-stop window for diagnostics; non-debug builds fail at the 1 ms budget. The daemon invokes declared hooks from a retained per-plugin VM; render remains cache-only, while update runs on the bounded background queue. Pre-exec hook failures and CPU-budget timeouts are audited and fail open.
