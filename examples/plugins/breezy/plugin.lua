function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.breezy",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "community bazaar/breezy repository status template",
  capabilities = {
    fs_read = { ".bzr/branch", ".bzr/checkout", ".bzr/repository" },
    fs_watch = { ".bzr/branch", ".bzr/checkout", ".bzr/repository" },
    exec = { "brz", "bzr" },
    net = false,
    secrets = false,
    env_read = { "PATH" },
    pre_exec = false,
  },
  modules = { "breezy_status" },
  render = "render",
  update = "update",
}
