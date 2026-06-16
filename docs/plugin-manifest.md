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
  render = "render",
  update = "update",
}
```

Required fields:

- `name`: lowercase id, `[a-z0-9][a-z0-9._-]*`.
- `version`: semver.
- `api_version`: supported Shisa plugin API major, currently `1`.
- `license`: SPDX-like identifier.
- `capabilities`: capability table. Omitted capabilities deny access.
- `modules`: non-empty exported module id list.
- `render`: Lua function name, defaults to `render`.

Optional fields:

- `update`: Lua function name for async/cache refresh.
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

Validation rejects malformed names, unsupported API versions, duplicate modules, invalid entry points, and malformed capability entries.

Capability checks:

- Missing capability fields deny access.
- `fs_read` and `fs_watch` match exact paths or recursive scopes ending in `/**`.
- `~/` resolves against the loading user's home directory.
- Relative filesystem scopes resolve under the plugin directory.
- `exec`, `net`, and `env_read` are exact allow-lists.
