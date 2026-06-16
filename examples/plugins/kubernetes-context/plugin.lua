function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

return {
  name = "shisa.kubernetes-context",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "reference kubernetes context and namespace plugin",
  capabilities = {
    fs_read = { "~/.kube/config" },
    fs_watch = { "~/.kube/config" },
    exec = false,
    net = false,
    secrets = false,
    env_read = { "KUBECONFIG" },
    pre_exec = false,
  },
  modules = { "k8s_ctx" },
  render = "render",
  update = "update",
}
