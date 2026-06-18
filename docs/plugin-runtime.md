# Plugin Runtime

Shisa embeds Lua through a dynamically loaded LuaJIT runtime.

Runtime choice:

- LuaJIT is selected in `src/plugin/lua.zig`.
- The local [Lua VM benchmark](lua-vm-benchmark.md) measured LuaJIT faster than Lua 5.4 on manifest validation, render string assembly, and capability path checks.
- Lua 5.4 remains a comparison baseline for future benchmark reruns.
- The daemon treats Lua as an untrusted extension runtime. Capabilities are enforced by Shisa host APIs, not by Lua conventions.

Loading:

- Runtime lookup tries common Homebrew LuaJIT library paths, then `libluajit-5.1.dylib`, `libluajit.dylib`, `libluajit-5.1.so`, and `libluajit-5.1.so.2`.
- If LuaJIT is unavailable, runtime tests skip and plugin loading must fail closed.

Sandbox:

- `Runtime.initSandboxed` opens standard libraries, then removes `os`, `io`, `package`, `debug`, `require`, `dofile`, and `loadfile` from the global table.
- `Runtime.initSandboxedWithOptions(.require_root)` keeps a wrapped `require` that accepts module names only and resolves through `<root>/?.lua` and `<root>/?/init.lua`.
- Host APIs must still enforce the manifest capability gate for filesystem, exec, network, env, secrets, and pre-exec access.
- `Runtime.loadManifestStrict` rejects unknown top-level manifest fields and unknown capability fields.

Lifecycle budget:

| Hook | Max wall time |
| --- | --- |
| `on_load` | 1 ms |
| `render` | 1 ms |
| `update` | 1 ms |
| `pre_exec` | 1 ms |
| `on_unload` | 1 ms |

The default runtime budget is 1 ms per Lua call. Debug builds use a 5 ms hard-stop window; non-debug builds fail at the 1 ms budget.
