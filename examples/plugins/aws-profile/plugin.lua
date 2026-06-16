function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.aws-profile",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "reference aws profile and region plugin",
  capabilities = {
    fs_read = { "~/.aws/config", "~/.aws/credentials" },
    fs_watch = { "~/.aws/config", "~/.aws/credentials" },
    exec = false,
    net = false,
    secrets = false,
    env_read = { "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION" },
    pre_exec = false,
  },
  modules = { "aws_profile" },
  render = "render",
  update = "update",
}
