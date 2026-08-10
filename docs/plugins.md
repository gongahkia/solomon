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

New plugin authors should start with [Authoring Plugins](authoring-plugins.md). Direct-distribution capability and support expectations live in [Plugin Policy](plugin-policy.md).

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

For non-interactive installation (this does not grant runtime trust):

```sh
shisa plugin install ./demo-plugin --yes
shisa plugin trust demo-plugin
```

For strict manifest audits:

```sh
shisa plugin install ./demo-plugin --yes --plugin-sandbox-strict
shisa plugin trust demo-plugin
```

Strict mode rejects unknown top-level manifest fields and unknown capability fields.

Common commands:

```sh
shisa plugin new demo-plugin
shisa plugin lint demo-plugin
shisa plugin doctor demo-plugin
shisa plugin pack demo-plugin
shisa plugin install ./demo-plugin-0.1.0.shisa-plugin
shisa plugin list
shisa plugin disable demo-plugin
shisa plugin enable demo-plugin
shisa plugin trust demo-plugin
```

`shisa plugin pack <path>` writes `<name>-<version>.shisa-plugin`, a tar bundle with `SHISA_PLUGIN_BUNDLE.json` containing file SHA-256 values and an Ed25519 signature over the canonical bundle manifest. `shisa plugin install <directory-or-bundle>` accepts only an explicit local directory or `.shisa-plugin` bundle; it rejects named entries, indexes, and remote Git URLs. Bundle installation accepts regular files only, rejects traversal paths, and verifies the payload hashes, manifest identity, and signature before installation.

`shisa plugin doctor [path]` defaults to the current directory and prefixes strict lint output with `doctor ok` or `doctor warnings`.

`shisa plugin verify <path>` strict-loads the manifest and rejects direct `os.execute` or `io.popen` use in `plugin.lua`.

`shisa plugin trust <name>` approves the exact manifest currently installed at that plugin path. `shisa plugin trust <name> --net=<provider>` records provider-scoped network trust for a net-only manifest. A grant for `openai` does not cover another provider such as `anthropic`, and it does not cover non-network capability changes. Core prompt configuration never enables network access; plugins require their own explicit capability and trust grants.

`shisa plugin list` prints `verified` for plugins recorded in `plugins.verified`; this is a local maintainer-review marker, not a registry listing or a statement that a plugin is safe in every environment.

## Runtime and Host APIs

The daemon keeps one sandboxed Lua VM for each loaded plugin. It calls `on_load` after validation, `render` while composing configured plugin segments at their declared position in `[prompt].modules` or `right_modules`, `update` on a bounded two-worker refresh queue, `pre_exec` before command execution, and `on_unload` during reload or shutdown.

`render(ctx)` is cache-only: filesystem, environment, secret, exec, and network APIs return an error there. `update` may use declared capabilities; `net.get` accepts HTTPS only and runs outside the prompt path. `fs.watch` records a native watcher registration, which is applied by the daemon and schedules a later update after debounce. `ctx.cache.get(key)` and `ctx.cache.set(key, value)` are available in every hook.

Available APIs are `ctx.fs.read(path)`, `ctx.fs.watch(path)`, `ctx.env.get(name)`, `ctx.secrets.get(name)`, `ctx.exec.run(command, args)`, `ctx.net.get(https_url)`, and the cache methods. Every call passes the manifest capability gate. Secrets are read only from `.env`, checking the plugin's `.env` before `<cwd>/.env`; they are never read from ambient environment variables through `ctx.secrets`.

Plugin settings use an isolated TOML namespace:

```toml
[plugins."demo-plugin"]
label = "ops"
```

The resulting values appear as `ctx.config.label`. A plugin pre-exec denial can block a command unless the shell request is forced. Plugin hook errors and CPU-budget timeouts fail open for commands and are appended to the local plugin pre-exec audit log.

## Reference Plugins

Reference manifests live under `examples/plugins/`:

- `git`: git branch and dirty-state capabilities.
- `language_versions`: python/node/rust/go probe capabilities.
- `kubectx`: Kubernetes context and namespace capabilities.
- `aws-profile`: AWS config/env capabilities.
- `a11y-live`: optional accessibility live-announcer template for risk-tier transitions.
- `fossil`: community Fossil VCS status template.
- `pijul`: community Pijul VCS status template.
- `breezy`: community Bazaar/Breezy VCS status template.

The repo-shaped starter template lives under `examples/shisa-plugin-template/`.
