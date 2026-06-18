local iterations = tonumber(arg[1]) or 500000

local function printf(fmt, ...)
  io.write(string.format(fmt, ...))
  io.write("\n")
end

local function recursive_match(pattern, path)
  if pattern:sub(-3) == "/**" then
    local prefix = pattern:sub(1, #pattern - 3)
    return path == prefix or path:sub(1, #prefix + 1) == prefix .. "/"
  end
  return pattern == path
end

local function bench(name, fn)
  collectgarbage("collect")
  fn(math.max(1000, math.floor(iterations / 20)))
  collectgarbage("collect")
  local start = os.clock()
  local checksum = fn(iterations)
  local elapsed = os.clock() - start
  printf("%s iterations=%d elapsed_ms=%.3f ns_per_iter=%.1f checksum=%d", name, iterations, elapsed * 1000, elapsed * 1000000000 / iterations, checksum)
end

bench("manifest_validate", function(n)
  local manifest = {
    name = "git",
    version = "1.0.0",
    api_version = 1,
    license = "MIT",
    modules = { "git_branch", "git_status" },
    capabilities = {
      fs_read = { "/repo/**", "~/.config/shisa/**" },
      fs_watch = { "/repo/.git/**" },
      exec = { "git" },
      env_read = { "GIT_DIR" },
      secrets = false,
      pre_exec = false,
    },
    render = "render",
    update = "update",
  }
  local sum = 0
  for i = 1, n do
    if not manifest.name:match("^[a-z0-9][a-z0-9._-]*$") then error("bad name") end
    if manifest.api_version ~= 1 then error("bad api") end
    if #manifest.modules == 0 then error("missing modules") end
    sum = sum + #manifest.name + #manifest.version + #manifest.license + #manifest.modules[(i % #manifest.modules) + 1]
    sum = sum + #manifest.capabilities.fs_read[(i % 2) + 1]
    sum = sum + #manifest.render + #manifest.update
  end
  return sum
end)

bench("render_concat", function(n)
  local dirs = { "/repo", "/repo/src", "/repo/docs" }
  local branches = { "main", "feature/lua", "release" }
  local versions = { "zig:0.15.1", "node:24.2.0", "python:3.13" }
  local sum = 0
  for i = 1, n do
    local parts = {
      dirs[(i % 3) + 1],
      "git:" .. branches[(i % 3) + 1],
      versions[(i % 3) + 1],
      "jobs:" .. tostring(i % 4),
      "took:" .. tostring(i % 1000) .. "ms",
    }
    local prompt = table.concat(parts, " ") .. "> "
    sum = sum + #prompt
  end
  return sum
end)

bench("capability_gate", function(n)
  local patterns = { "/repo/**", "/repo/.git/**", "~/.config/shisa/**", "/tmp/shisa.sock" }
  local paths = { "/repo/src/main.zig", "/repo/.git/HEAD", "~/.config/shisa/plugin.lua", "/tmp/shisa.sock", "/etc/passwd" }
  local sum = 0
  for i = 1, n do
    local path = paths[(i % #paths) + 1]
    local allowed = false
    for _, pattern in ipairs(patterns) do
      if recursive_match(pattern, path) then
        allowed = true
        break
      end
    end
    if allowed then sum = sum + #path else sum = sum - 1 end
  end
  return sum
end)
