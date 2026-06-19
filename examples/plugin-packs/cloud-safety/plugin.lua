local rules = {
  {
    module = "k8s_namespace_risk",
    pattern = "%f[%w]kubectl%f[%W].-%f[%w]delete%f[%W]",
    message = "cloud-safety: kubectl delete needs review",
  },
  {
    module = "k8s_namespace_risk",
    pattern = "%-%-namespace[=%s]+prod",
    message = "cloud-safety: kubernetes prod namespace",
  },
  {
    module = "k8s_namespace_risk",
    pattern = "%f[%w]%-n%s+prod%f[%W]",
    message = "cloud-safety: kubernetes prod namespace",
  },
  {
    module = "iam_principal",
    pattern = "%f[%w]aws%f[%W].-%f[%w]iam%f[%W].-%f[%w]delete",
    message = "cloud-safety: destructive IAM command",
  },
  {
    module = "iam_principal",
    pattern = "%f[%w]aws%f[%W].-%f[%w]sts%f[%W].-%f[%w]assume%-role",
    message = "cloud-safety: IAM principal switch",
  },
  {
    module = "prod_warning",
    pattern = "%f[%w]terraform%f[%W].-%f[%w]destroy%f[%W]",
    message = "cloud-safety: terraform destroy needs review",
  },
  {
    module = "prod_warning",
    pattern = "prod",
    message = "cloud-safety: command mentions prod",
  },
}

local function command_text(ctx)
  if ctx == nil then
    return ""
  end
  if type(ctx.command) == "string" then
    return ctx.command
  end
  if type(ctx.argv) ~= "table" then
    return ""
  end
  local parts = {}
  for index, value in ipairs(ctx.argv) do
    parts[index] = tostring(value)
  end
  return table.concat(parts, " ")
end

function render(ctx)
  return nil
end

function update(ctx)
  return nil
end

function pre_exec(ctx)
  local text = string.lower(command_text(ctx))
  if text == "" then
    return nil
  end
  for _, rule in ipairs(rules) do
    if string.find(text, rule.pattern) ~= nil then
      return {
        allow = false,
        module = rule.module,
        message = rule.message,
      }
    end
  end
  return nil
end

return {
  name = "shisa.cloud-safety",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "opt-in cloud safety pre-exec pack",
  capabilities = {
    fs_read = {},
    fs_watch = {},
    exec = false,
    net = false,
    secrets = false,
    env_read = { "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "KUBECONFIG" },
    pre_exec = true,
  },
  modules = { "prod_warning", "k8s_namespace_risk", "iam_principal" },
  render = "render",
  update = "update",
  pre_exec = "pre_exec",
}
