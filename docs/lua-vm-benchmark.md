# Lua VM Benchmark

Benchmark script: `bench/lua-vm-hot-paths.lua`.

Environment:

- Date: 2026-06-18.
- Host: macOS 26.5.1, arm64.
- Lua 5.4.8: built in `/tmp/shisa-lua-bench` from `lua-5.4.8.tar.gz`, SHA-256 `4f18ddae154e793e46eeab727c59ef1c0c0c2b744e7b94219710d76f530629ae`.
- LuaJIT: `/opt/homebrew/bin/luajit`, `LuaJIT 2.1.1781602682`.
- Iterations: 500000 per case.
- Samples: 5 sequential runs per VM; table reports median `ns_per_iter`.

Command:

```sh
/tmp/shisa-lua-bench/lua-5.4.8/src/lua bench/lua-vm-hot-paths.lua 500000
/opt/homebrew/bin/luajit bench/lua-vm-hot-paths.lua 500000
```

| Case | Lua 5.4.8 median ns/iter | LuaJIT median ns/iter | LuaJIT speedup |
| --- | ---: | ---: | ---: |
| `manifest_validate` | 274.0 | 141.2 | 1.94x |
| `render_concat` | 1136.5 | 589.8 | 1.93x |
| `capability_gate` | 968.5 | 172.5 | 5.61x |

Raw sequential samples:

```text
lua54
manifest_validate iterations=500000 elapsed_ms=147.814 ns_per_iter=295.6 checksum=23000000
render_concat iterations=500000 elapsed_ms=700.559 ns_per_iter=1401.1 checksum=25945007
capability_gate iterations=500000 elapsed_ms=484.232 ns_per_iter=968.5 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=155.020 ns_per_iter=310.0 checksum=23000000
render_concat iterations=500000 elapsed_ms=518.061 ns_per_iter=1036.1 checksum=25945007
capability_gate iterations=500000 elapsed_ms=313.273 ns_per_iter=626.5 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=116.064 ns_per_iter=232.1 checksum=23000000
render_concat iterations=500000 elapsed_ms=568.256 ns_per_iter=1136.5 checksum=25945007
capability_gate iterations=500000 elapsed_ms=493.210 ns_per_iter=986.4 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=137.008 ns_per_iter=274.0 checksum=23000000
render_concat iterations=500000 elapsed_ms=554.990 ns_per_iter=1110.0 checksum=25945007
capability_gate iterations=500000 elapsed_ms=399.843 ns_per_iter=799.7 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=120.256 ns_per_iter=240.5 checksum=23000000
render_concat iterations=500000 elapsed_ms=606.131 ns_per_iter=1212.3 checksum=25945007
capability_gate iterations=500000 elapsed_ms=515.306 ns_per_iter=1030.6 checksum=7300000

luajit
manifest_validate iterations=500000 elapsed_ms=70.370 ns_per_iter=140.7 checksum=23000000
render_concat iterations=500000 elapsed_ms=288.736 ns_per_iter=577.5 checksum=25945007
capability_gate iterations=500000 elapsed_ms=88.070 ns_per_iter=176.1 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=69.488 ns_per_iter=139.0 checksum=23000000
render_concat iterations=500000 elapsed_ms=278.915 ns_per_iter=557.8 checksum=25945007
capability_gate iterations=500000 elapsed_ms=83.887 ns_per_iter=167.8 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=70.839 ns_per_iter=141.7 checksum=23000000
render_concat iterations=500000 elapsed_ms=294.921 ns_per_iter=589.8 checksum=25945007
capability_gate iterations=500000 elapsed_ms=84.408 ns_per_iter=168.8 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=70.576 ns_per_iter=141.2 checksum=23000000
render_concat iterations=500000 elapsed_ms=304.319 ns_per_iter=608.6 checksum=25945007
capability_gate iterations=500000 elapsed_ms=86.239 ns_per_iter=172.5 checksum=7300000
manifest_validate iterations=500000 elapsed_ms=71.855 ns_per_iter=143.7 checksum=23000000
render_concat iterations=500000 elapsed_ms=297.044 ns_per_iter=594.1 checksum=25945007
capability_gate iterations=500000 elapsed_ms=89.903 ns_per_iter=179.8 checksum=7300000
```
