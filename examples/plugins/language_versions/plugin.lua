function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.language-versions",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "reference python/node/rust/go version probe plugin",
  capabilities = {
    fs_read = {
      "pyproject.toml",
      "requirements.txt",
      "setup.py",
      "package.json",
      "Cargo.toml",
      "go.mod",
    },
    fs_watch = {
      "pyproject.toml",
      "requirements.txt",
      "setup.py",
      "package.json",
      "Cargo.toml",
      "go.mod",
    },
    exec = { "python3", "node", "rustc", "go" },
    net = false,
    secrets = false,
    env_read = { "PATH" },
    pre_exec = false,
  },
  modules = { "language_versions" },
  render = "render",
  update = "update",
}
