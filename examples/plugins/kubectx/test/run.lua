local plugin_path = arg[1] or "plugin.lua"

local function read_file(path)
  local file = assert(io.open(path, "rb"))
  local text = assert(file:read("*a"))
  assert(file:close())
  return text
end

local function assert_eq(actual, expected, name)
  if actual ~= expected then
    error(name .. ": expected " .. expected .. ", got " .. tostring(actual), 2)
  end
end

_G.SHISA_KUBECTX_TEST = true
local kubectx = assert(loadfile(plugin_path))()
_G.SHISA_KUBECTX_TEST = nil

local kubeconfig = [[
apiVersion: v1
kind: Config
contexts:
- context:
    cluster: prod
    namespace: payments
    user: deployer
  name: prod-admin
current-context: prod-admin
]]

assert_eq(kubectx.render_from_sources({ kubeconfig }), "k8s:prod-admin/payments", "basic render")

local no_namespace = [[
contexts:
- name: dev
  context:
    cluster: dev
    user: local
current-context: dev
]]

assert_eq(kubectx.render_from_sources({ no_namespace }), "k8s:dev/default", "default namespace")

local quoted = [[
contexts:
- name: "stage:blue"
  context:
    namespace: 'team one'
current-context: "stage:blue"
]]

assert_eq(kubectx.render_from_sources({ quoted }), "k8s:stage:blue/team one", "quoted scalars")

local first = [[
contexts:
- name: prod
  context:
    namespace: prod-ns
current-context: prod
]]

local second = [[
contexts:
- name: stage
  context:
    namespace: stage-ns
- name: prod
  context:
    namespace: ignored
current-context: stage
]]

assert_eq(kubectx.render_from_sources({ first, second }), "k8s:prod/prod-ns", "multi-file first current-context")
assert_eq(kubectx.render_from_sources({ "" }), "", "empty source")
assert_eq(kubectx.render_from_sources({ "current-context: missing\n" }), "", "missing context")

local paths = kubectx.source_paths("/tmp/a::/tmp/b:")
assert_eq(#paths, 2, "kubeconfig split count")
assert_eq(paths[1], "/tmp/a", "kubeconfig split first")
assert_eq(paths[2], "/tmp/b", "kubeconfig split second")
assert_eq(kubectx.source_paths(nil)[1], "~/.kube/config", "default kubeconfig")

local source = read_file(plugin_path)
assert(not source:find("os%.execute"), "plugin must not call os.execute")
assert(not source:find("kubectl%s+config"), "plugin must not shell out to kubectl")

local manifest = assert(loadfile(plugin_path))()
assert_eq(manifest.name, "kubectx", "manifest name")
assert_eq(manifest.capabilities.exec, false, "manifest exec deny")
assert_eq(manifest.capabilities.net, false, "manifest net deny")
assert_eq(manifest.capabilities.env_read[1], "KUBECONFIG", "manifest env_read")
assert_eq(manifest.capabilities.fs_read[1], "~/.kube/**", "manifest fs_read kube dir")
assert_eq(manifest.capabilities.fs_read[2], "$KUBECONFIG", "manifest fs_read env path")

print("ok")
