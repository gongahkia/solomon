# Plugin SDK

Plugins are Lua bundles installed under the Shisa config directory:

```text
~/.config/shisa/plugins/<plugin-name>/
  plugin.lua
```

The daemon loads plugin metadata from `plugin.lua`, validates it with the manifest schema, and runs Lua in a sandboxed LuaJIT runtime. Filesystem, exec, network, env, secrets, and pre-exec access must be declared in the manifest and checked through the capability gate.

## Manifest

`plugin.lua` returns a table:

```lua
return {
  name = "demo-plugin",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  capabilities = {
    fs_read = {},
    fs_watch = {},
    exec = false,
    net = false,
    secrets = false,
    env_read = {},
    pre_exec = false,
  },
  modules = { "demo" },
  render = "render",
  update = "update",
}
```

Required fields:

- `name`: lowercase plugin id, `[a-z0-9][a-z0-9._-]*`.
- `version`: semver.
- `api_version`: currently `1`.
- `license`: SPDX-like id.
- `modules`: non-empty list of exported module ids.

Optional fields:

- `capabilities`: omitted fields deny access.
- `render`: Lua function name, defaults to `render`.
- `update`: Lua function name for async refresh.
- `description`, `author`, `homepage`, `repository`.

See `docs/plugin-manifest.md` for exact validation rules.

Marketplace review and delisting rules live in [Plugin Policy](plugin-policy.md).

## Sandbox

The sandbox removes these globals:

- `os`
- `io`
- `package`
- `require`
- `dofile`
- `loadfile`

This prevents direct shell/file loading APIs. Host access must go through Shisa APIs guarded by manifest capabilities.

## Tutorial

Create a plugin repo:

```sh
mkdir demo-plugin
cd demo-plugin
cat > plugin.lua <<'LUA'
return {
  name = "demo-plugin",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  capabilities = {
    exec = false,
    net = false,
  },
  modules = { "demo" },
}
LUA
git init
git add plugin.lua
git commit -m 'init plugin'
```

Install it:

```sh
shisa plugin install ./demo-plugin
```

For scripts or tests:

```sh
shisa plugin install ./demo-plugin --yes
```

For strict manifest audits:

```sh
shisa plugin install ./demo-plugin --yes --plugin-sandbox-strict
```

Strict mode rejects unknown top-level manifest fields and unknown capability fields.

Inspect state:

```sh
shisa plugin list
shisa plugin disable demo-plugin
shisa plugin enable demo-plugin
shisa plugin trust demo-plugin
```

## Current Limits

- Plugin render functions are not yet wired into the daemon render pipeline.
- Host API bindings for filesystem, exec, network, env, secrets, and pre-exec are not exposed to Lua yet.
- `shisa plugin install` audits `plugin.lua` by sandbox-loading and validating the returned manifest table before installing.

## Reference Plugins

Reference manifests live under `examples/plugins/`:

- `git`: git branch and dirty-state capabilities.
- `language_versions`: python/node/rust/go probe capabilities.
- `kubernetes-context`: kubeconfig/env capabilities.
- `aws-profile`: AWS config/env capabilities.
- `a11y-live`: optional accessibility live-announcer template for risk-tier transitions.
- `fossil`: community Fossil VCS status template.
- `pijul`: community Pijul VCS status template.
- `breezy`: community Bazaar/Breezy VCS status template.
