local shisa = require("shisa")

shisa.setup({
  topics = { "cloud_ctx", "vcs.summary", "risk_tier" },
  auto_connect = true,
})

local ShisaStatus = {
  provider = function()
    return shisa.statusline()
  end,
}

require("heirline").setup({
  statusline = {
    { provider = "%f" },
    { provider = " " },
    ShisaStatus,
  },
})
