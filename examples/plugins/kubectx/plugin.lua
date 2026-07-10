local M = {}

local cached_segment = ""

local function trim(value)
  return (value or ""):match("^%s*(.-)%s*$")
end

local function strip_comment(value)
  local quote = nil
  local escaped = false
  for i = 1, #value do
    local ch = value:sub(i, i)
    if escaped then
      escaped = false
    elseif ch == "\\" and quote == '"' then
      escaped = true
    elseif quote then
      if ch == quote then quote = nil end
    elseif ch == '"' or ch == "'" then
      quote = ch
    elseif ch == "#" then
      return trim(value:sub(1, i - 1))
    end
  end
  return trim(value)
end

local function unescape_double_quoted(value)
  return (value:gsub("\\n", "\n"):gsub("\\t", "\t"):gsub('\\"', '"'):gsub("\\\\", "\\"))
end

local function scalar(value)
  value = strip_comment(value)
  if value == "~" or value == "null" or value == "Null" or value == "NULL" then return "" end
  if #value >= 2 then
    local first = value:sub(1, 1)
    local last = value:sub(-1)
    if first == '"' and last == '"' then return unescape_double_quoted(value:sub(2, -2)) end
    if first == "'" and last == "'" then return value:sub(2, -2):gsub("''", "'") end
  end
  return value
end

local function key_value(body)
  local key, value = body:match("^([%w_-]+)%s*:%s*(.*)$")
  if not key then return nil, nil end
  return key, scalar(value)
end

local function line_indent(line)
  return #(line:match("^(%s*)") or "")
end

local function finish_context(config, item)
  if item and item.name and item.name ~= "" and not config.contexts[item.name] then
    config.contexts[item.name] = { namespace = item.namespace }
  end
end

function M.parse_kubeconfig(text)
  local config = { current_context = nil, contexts = {} }
  local in_contexts = false
  local contexts_indent = nil
  local item = nil

  for raw in (text or ""):gmatch("([^\n]*)\n?") do
    if raw == "" and text and text:sub(-1) ~= "\n" then break end
    local line = raw:gsub("\r$", "")
    if line:match("^%s*$") or line:match("^%s*#") then goto continue end

    local indent = line_indent(line)
    local body = line:sub(indent + 1)
    local top_key, top_value = key_value(body)
    if indent == 0 then
      if in_contexts and body:sub(1, 1) == "-" then
      elseif top_key == "current-context" then
        if in_contexts then finish_context(config, item) end
        in_contexts = false
        item = nil
        config.current_context = top_value
      elseif top_key == "contexts" then
        finish_context(config, item)
        in_contexts = true
        contexts_indent = indent
        item = nil
      else
        if in_contexts then finish_context(config, item) end
        in_contexts = false
        item = nil
      end
    elseif in_contexts and contexts_indent and indent <= contexts_indent then
      finish_context(config, item)
      in_contexts = false
      item = nil
    end

    if in_contexts then
      if body:sub(1, 1) == "-" then
        finish_context(config, item)
        item = { name = nil, namespace = nil }
        local rest = trim(body:sub(2))
        local key, value = key_value(rest)
        if key == "name" then
          item.name = value
        elseif key == "namespace" then
          item.namespace = value
        end
      elseif item then
        local key, value = key_value(body)
        if key == "name" then
          item.name = value
        elseif key == "namespace" then
          item.namespace = value
        end
      end
    end

    ::continue::
  end

  if in_contexts then finish_context(config, item) end
  return config
end

function M.merge_configs(configs)
  local merged = { current_context = nil, contexts = {} }
  for _, config in ipairs(configs or {}) do
    if merged.current_context == nil and config.current_context ~= nil then
      merged.current_context = config.current_context
    end
    for name, context in pairs(config.contexts or {}) do
      if not merged.contexts[name] then merged.contexts[name] = context end
    end
  end
  return merged
end

function M.render_config(config)
  local current = config and config.current_context
  if not current or current == "" then return "" end
  local context = config.contexts[current]
  if not context then return "" end
  local namespace = context.namespace
  if not namespace or namespace == "" then namespace = "default" end
  return "k8s:" .. current .. "/" .. namespace
end

function M.render_from_sources(sources)
  local configs = {}
  for _, text in ipairs(sources or {}) do
    if text and text ~= "" then configs[#configs + 1] = M.parse_kubeconfig(text) end
  end
  if #configs == 0 then return "" end
  return M.render_config(M.merge_configs(configs))
end

function M.source_paths(kubeconfig)
  local paths = {}
  if kubeconfig and kubeconfig ~= "" then
    for path in kubeconfig:gmatch("([^:]+)") do
      if path ~= "" then paths[#paths + 1] = path end
    end
  else
    paths[1] = "~/.kube/config"
  end
  return paths
end

local function ctx_call(ctx, names, ...)
  if type(ctx) ~= "table" then return nil end
  for _, name in ipairs(names) do
    local fn = ctx[name]
    if type(fn) == "function" then
      local ok, result = pcall(fn, ctx, ...)
      if ok then return result end
    end
  end
  return nil
end

local function ctx_env(ctx, name)
  if type(ctx) == "table" and type(ctx.env) == "table" then return ctx.env[name] end
  return ctx_call(ctx, { "read_env", "env_read", "getenv" }, name)
end

local function ctx_read_file(ctx, path)
  return ctx_call(ctx, { "read_file", "fs_read", "read" }, path)
end

function M.render_from_context(ctx)
  local paths = M.source_paths(ctx_env(ctx, "KUBECONFIG"))
  local sources = {}
  for _, path in ipairs(paths) do
    local text = ctx_read_file(ctx, path)
    if text and text ~= "" then sources[#sources + 1] = text end
  end
  return M.render_from_sources(sources)
end

function update(ctx)
  cached_segment = M.render_from_context(ctx)
  return cached_segment
end

function render(ctx)
  if cached_segment ~= "" then return cached_segment end
  return M.render_from_context(ctx)
end

if rawget(_G, "SHISA_KUBECTX_TEST") then return M end

return {
  name = "kubectx",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  description = "Kubernetes current context and namespace prompt segment.",
  author = "Gong Ah Kia",
  homepage = "https://github.com/gongahkia/shisa/tree/main/examples/plugins/kubectx",
  repository = "https://github.com/gongahkia/shisa",
  capabilities = {
    fs_read = { "~/.kube/**", "$KUBECONFIG" },
    fs_watch = { "~/.kube/**", "$KUBECONFIG" },
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
