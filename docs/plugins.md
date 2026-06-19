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
  on_load = "on_load",
  render = "render",
  update = "update",
  on_unload = "on_unload",
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
- `on_load`: Lua function name for load-time setup.
- `render`: Lua function name, defaults to `render`.
- `update`: Lua function name for async refresh.
- `pre_exec`: Lua function name for command preflight, requiring `capabilities.pre_exec = true`.
- `on_unload`: Lua function name for cleanup.
- `description`, `author`, `homepage`, `repository`.

See `docs/plugin-manifest.md` for exact validation rules.
Lifecycle hook wall-time limits are documented in [Plugin Manifest](plugin-manifest.md).

New plugin authors should start with [Authoring Plugins](authoring-plugins.md). Marketplace review and delisting rules live in [Plugin Policy](plugin-policy.md).

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

Common commands:

```sh
shisa plugin new demo-plugin
shisa plugin lint demo-plugin
shisa plugin doctor demo-plugin
shisa plugin search git
shisa plugin install git-tools
shisa plugin pack demo-plugin
shisa plugin list
shisa plugin disable demo-plugin
shisa plugin enable demo-plugin
shisa plugin trust demo-plugin
shisa plugin trust shisa.ai --net=openai
```

`shisa plugin pack <path>` writes `<name>-<version>.shisa-plugin`, a tar bundle with `SHISA_PLUGIN_BUNDLE.json` containing file SHA-256 values and an Ed25519 signature over the canonical bundle manifest.

`shisa plugin doctor [path]` defaults to the current directory and prefixes strict lint output with `doctor ok` or `doctor warnings`.

`shisa plugin search <query> [--index <path>]` reads a marketplace JSON index. By default the index path is `plugins.index.json` next to `shisa.toml`; the checked-in seed index lives at `docs/plugins/index.json`.

`shisa plugin install <name> [--index <path>]` resolves `<name>` through the marketplace index, then clones the entry URL. Direct URLs and explicit paths still bypass the index.

`shisa plugin trust <name> --net=<provider>` records provider-scoped network trust. A grant for `openai` does not cover another provider such as `anthropic`, and it does not cover non-network capability changes. `[ai].provider` may select a cloud provider only when `[ai].plugin` names a trusted plugin with the matching `net=<provider>` grant.

`shisa plugin list` prints `verified` for plugins recorded in `plugins.verified`. Marketplace sync is expected to maintain that file once the repo index workflow lands.

Marketplace entries must include `manifest_sha256` plus Minisign or Sigstore signature metadata. See [Plugin Signing](plugin-signing.md).

## Current Limits

- Plugin lifecycle hook names are validated and stored, but hook invocation is not yet wired into the daemon pipeline.
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

The repo-shaped starter template lives under `examples/shisa-plugin-template/`.
