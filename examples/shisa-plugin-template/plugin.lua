local state = {
  loaded = false,
}

function on_load(ctx)
  state.loaded = true
  return nil
end

function render(ctx)
  if not state.loaded then
    return nil
  end
  return "template"
end

function update(ctx)
  return nil
end

function on_unload(ctx)
  state.loaded = false
  return nil
end

return {
  name = "shisa-plugin-template",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "starter Shisa plugin template",
  capabilities = {
    fs_read = {},
    fs_watch = {},
    exec = false,
    net = false,
    secrets = false,
    env_read = {},
    pre_exec = false,
  },
  modules = { "template" },
  on_load = "on_load",
  render = "render",
  update = "update",
  on_unload = "on_unload",
}
