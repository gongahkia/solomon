function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.pijul",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "community pijul repository status template",
  capabilities = {
    fs_read = { ".pijul/config", ".pijul/changes", ".pijul/pristine" },
    fs_watch = { ".pijul/config", ".pijul/changes", ".pijul/pristine" },
    exec = { "pijul" },
    net = false,
    secrets = false,
    env_read = { "PATH" },
    pre_exec = false,
  },
  modules = { "pijul_status" },
  render = "render",
  update = "update",
}
