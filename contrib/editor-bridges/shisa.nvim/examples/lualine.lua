local shisa = require("shisa")

shisa.setup({
  topics = { "cloud_ctx", "vcs.summary", "risk_tier" },
  auto_connect = true,
})

require("lualine").setup({
  sections = {
    lualine_c = {
      "filename",
      shisa.statusline,
    },
  },
})
