local M = {}

local defaults = {
  socket = nil,
  topics = { "cloud_ctx", "vcs.summary", "risk_tier" },
  backpressure_limit = 16,
  dirchanged_refresh = true,
}

M.config = vim.deepcopy(defaults)
M.state = {
  channel = nil,
  lines = "",
  values = {},
}

local function default_socket()
  if vim.fn.has("macunix") == 1 then
    return vim.env.HOME .. "/Library/Caches/shisa/shisa.sock"
  end
  if vim.env.XDG_RUNTIME_DIR and vim.env.XDG_RUNTIME_DIR ~= "" then
    return vim.env.XDG_RUNTIME_DIR .. "/shisa.sock"
  end
  local uid = vim.fn.systemlist({ "id", "-u" })[1] or ""
  return "/run/user/" .. uid .. "/shisa.sock"
end

local function json_encode(value)
  if vim.json and vim.json.encode then
    return vim.json.encode(value)
  end
  return vim.fn.json_encode(value)
end

local function json_decode(value)
  if vim.json and vim.json.decode then
    return vim.json.decode(value)
  end
  return vim.fn.json_decode(value)
end

local function frame(payload)
  local len = #payload
  local b1 = math.floor(len / 16777216) % 256
  local b2 = math.floor(len / 65536) % 256
  local b3 = math.floor(len / 256) % 256
  local b4 = len % 256
  return string.char(b1, b2, b3, b4) .. payload
end

local function apply_event(line)
  local ok, event = pcall(json_decode, line)
  if not ok or type(event) ~= "table" or type(event.topic) ~= "string" then
    return
  end
  local data = type(event.data) == "table" and event.data or {}
  M.state.values[event.topic] = data.text or data.value or event.kind or ""
end

local function on_stdout(_, data, _)
  if type(data) ~= "table" then
    return
  end
  M.state.lines = M.state.lines .. table.concat(data, "\n")
  while true do
    local start_at, end_at = M.state.lines:find("\n", 1, true)
    if not start_at then
      break
    end
    local line = M.state.lines:sub(1, start_at - 1)
    M.state.lines = M.state.lines:sub(end_at + 1)
    if line ~= "" then
      apply_event(line)
    end
  end
end

function M.connect()
  if M.state.channel then
    return true
  end
  local socket = M.config.socket or default_socket()
  local channel = vim.fn.sockconnect("pipe", socket, {
    on_stdout = on_stdout,
    stdout_buffered = false,
  })
  if channel <= 0 then
    return false
  end
  M.state.channel = channel
  local payload = json_encode({
    v = 1,
    op = "subscribe",
    request_id = "shisa.nvim",
    topics = M.config.topics,
    backpressure_limit = M.config.backpressure_limit,
  })
  vim.fn.chansend(channel, frame(payload))
  return true
end

function M.disconnect()
  if not M.state.channel then
    return
  end
  vim.fn.chanclose(M.state.channel)
  M.state.channel = nil
end

function M.refresh()
  if not M.state.channel and not M.connect() then
    return false
  end
  local payload = json_encode({
    op = "ping",
    reason = "DirChanged",
  })
  vim.fn.chansend(M.state.channel, payload .. "\n")
  return true
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", vim.deepcopy(defaults), opts or {})
  if M.config.dirchanged_refresh then
    local group = vim.api.nvim_create_augroup("shisa_nvim", { clear = true })
    vim.api.nvim_create_autocmd("DirChanged", {
      group = group,
      callback = function()
        M.refresh()
      end,
    })
  end
  if M.config.auto_connect then
    M.connect()
  end
end

function M.statusline()
  local out = {}
  for _, topic in ipairs(M.config.topics) do
    local value = M.state.values[topic]
    if value and value ~= "" then
      table.insert(out, value)
    end
  end
  return table.concat(out, " ")
end

return M
