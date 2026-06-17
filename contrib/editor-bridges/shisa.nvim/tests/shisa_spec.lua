describe("shisa.nvim", function()
  before_each(function()
    package.loaded.shisa = nil
    vim.g.loaded_shisa_nvim = nil
  end)

  it("builds an empty statusline before events", function()
    local shisa = require("shisa")
    shisa.setup({
      topics = { "cloud_ctx", "vcs.summary", "risk_tier" },
      dirchanged_refresh = false,
    })
    assert.are.equal("", shisa.statusline())
  end)

  it("registers a DirChanged autocmd", function()
    local shisa = require("shisa")
    shisa.setup({
      dirchanged_refresh = true,
    })
    assert.are.equal(1, #vim.api.nvim_get_autocmds({
      group = "shisa_nvim",
      event = "DirChanged",
    }))
  end)
end)
