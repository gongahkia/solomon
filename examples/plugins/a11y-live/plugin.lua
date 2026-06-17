local last_risk_tier = nil

local function current_risk_tier(ctx)
  if type(ctx) ~= "table" then
    return nil
  end
  if type(ctx.risk_tier) == "string" then
    return ctx.risk_tier
  end
  if type(ctx.modules) == "table" and type(ctx.modules.risk_tier) == "string" then
    return ctx.modules.risk_tier
  end
  return nil
end

function render(ctx)
  return nil
end

function update(ctx)
  local tier = current_risk_tier(ctx)
  if tier == nil or tier == last_risk_tier then
    return nil
  end
  local previous = last_risk_tier
  last_risk_tier = tier
  local message = nil
  if previous == nil then
    message = "risk tier " .. tier
  else
    message = "risk tier changed from " .. previous .. " to " .. tier
  end
  if type(ctx) == "table" and type(ctx.announce) == "function" then
    ctx.announce(message)
  end
  return { a11y = message }
end

return {
  name = "shisa.a11y.live",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "optional accessibility live announcer for risk tier transitions",
  capabilities = {
    fs_read = {},
    fs_watch = {},
    exec = false,
    net = false,
    secrets = false,
    env_read = {},
    pre_exec = false,
  },
  modules = { "a11y_live" },
  render = "render",
  update = "update",
}
