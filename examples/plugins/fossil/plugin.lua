function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.fossil",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "community fossil repository status template",
  capabilities = {
    fs_read = { ".fslckout", "_FOSSIL_", ".fos" },
    fs_watch = { ".fslckout", "_FOSSIL_", ".fos" },
    exec = { "fossil" },
    net = false,
    secrets = false,
    env_read = { "PATH" },
    pre_exec = false,
  },
  modules = { "fossil_status" },
  render = "render",
  update = "update",
}
