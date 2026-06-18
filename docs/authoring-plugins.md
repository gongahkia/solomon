# Authoring Plugins

This quickstart creates a local plugin repo that passes Shisa's manifest audit.

## 1. Create the Plugin

```sh
mkdir shisa-demo-plugin
cd shisa-demo-plugin
cat > plugin.lua <<'LUA'
function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

function on_load(ctx)
  return nil
end

function on_unload(ctx)
  return nil
end

return {
  name = "demo-plugin",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "demo plugin",
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
LUA
git init
git add plugin.lua
git commit -m 'init plugin'
```

## 2. Audit the Manifest

From the Shisa repo:

```sh
zig build debug
./zig-out/bin/shisa plugin install /path/to/shisa-demo-plugin --yes --plugin-sandbox-strict
./zig-out/bin/shisa plugin list
```

Strict mode rejects unknown top-level manifest fields and unknown capability fields.

## 3. Keep Capabilities Narrow

Declare only what the plugin needs:

- use exact files before directory globs
- keep `exec`, `net`, `secrets`, and `pre_exec` disabled by default
- allow-list exact environment variable names
- document side effects in the README

Capability review follows [Plugin Policy](plugin-policy.md).

## 4. Prepare for Marketplace Review

Before submitting a marketplace entry:

- tag a release in the plugin repo
- include `README.md`, `LICENSE`, and `plugin.lua`
- explain each requested capability
- include screenshots or prompt output examples when the plugin renders user-visible text
- state whether the plugin reads secrets, cloud state, SSH config, or kubeconfig data

Reference plugins live under `examples/plugins/`.
