function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.git",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "reference git branch and dirty-state plugin",
  capabilities = {
    fs_read = { ".git/HEAD", ".git/index", ".git/packed-refs" },
    fs_watch = { ".git/HEAD", ".git/index", ".git/packed-refs", ".git/**" },
    exec = { "git" },
    net = false,
    secrets = false,
    env_read = {},
    pre_exec = false,
  },
  modules = { "git_branch" },
  render = "render",
  update = "update",
}
