if vim.g.loaded_shisa_nvim == 1 then
  return
end
vim.g.loaded_shisa_nvim = 1

vim.api.nvim_create_user_command("ShisaConnect", function()
  require("shisa").connect()
end, {})

vim.api.nvim_create_user_command("ShisaDisconnect", function()
  require("shisa").disconnect()
end, {})
