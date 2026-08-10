# Plugin in 30 Lines of Lua

Create a minimal plugin that passes Shisa manifest validation.

## 1. Write `plugin.lua`

```lua
function render(ctx)
  return "hello"
end

return {
  name = "hello",
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
  modules = { "hello" },
  render = "render",
}
```

This declares one module, no host access, and one render entry point.

## 2. Commit it as a plugin repo

```sh
mkdir hello-plugin
cd hello-plugin
$EDITOR plugin.lua
git init
git add plugin.lua
git commit -m "init plugin"
```

`shisa plugin install` clones a Git repo and audits `plugin.lua`.

## 3. Install and inspect

```sh
shisa plugin install . --yes --plugin-sandbox-strict
shisa plugin trust hello
shisa plugin list
```

Strict mode rejects unknown top-level manifest fields and unknown capability fields.

Plugin state commands:

```sh
shisa plugin disable hello
shisa plugin enable hello
shisa plugin trust hello
```

## 4. Keep capabilities narrow

Missing capability fields deny access. Prefer explicit denial for tutorials:

```lua
exec = false
net = false
secrets = false
pre_exec = false
```

Use exact allow-lists when a plugin needs host access.

## 5. Current runtime limit

The current plugin runtime installs, sandbox-loads, and validates plugin manifests. Plugin render functions are not yet wired into the daemon render pipeline.

See [Plugins](../plugins.md), [Plugin Manifest](../plugin-manifest.md), and [Capabilities](../capabilities.md).
