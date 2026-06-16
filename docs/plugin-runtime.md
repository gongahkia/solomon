# Plugin Runtime

Shisa embeds Lua through a dynamically loaded LuaJIT runtime.

Runtime choice:

- LuaJIT is used for the first plugin runtime because it is available on the local Homebrew toolchain and has a small C API surface for dynamic loading.
- Lua 5.4 remains compatible with the manifest model, but local verification found Lua 5.5 rather than Lua 5.4.
- The daemon treats Lua as an untrusted extension runtime. Capabilities are enforced by Shisa host APIs, not by Lua conventions.

Loading:

- Runtime lookup tries common Homebrew LuaJIT library paths, then `libluajit-5.1.dylib`, `libluajit.dylib`, `libluajit-5.1.so`, and `libluajit-5.1.so.2`.
- If LuaJIT is unavailable, runtime tests skip and plugin loading must fail closed.

Sandbox:

- `Runtime.initSandboxed` opens standard libraries, then removes `os`, `io`, `package`, `require`, `dofile`, and `loadfile` from the global table.
- Host APIs must still enforce the manifest capability gate for filesystem, exec, network, env, secrets, and pre-exec access.
- `Runtime.loadManifestStrict` rejects unknown top-level manifest fields and unknown capability fields.
