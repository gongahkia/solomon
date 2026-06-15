# Architecture

Shisa is a shell prompt split into a tiny shell hook and a long-running per-user daemon.

## Components

### Shell hook

The shell hook captures runtime state:

- current working directory
- last exit code
- background job count
- last command duration
- terminal size and capability hints

It sends that state to the daemon over a Unix-domain socket and prints the returned prompt. If the daemon is unreachable, the hook prints a minimal fallback prompt within 5 ms.

### Daemon

`shisad` owns:

- Unix-domain socket server
- render pipeline
- module scheduler
- filesystem watchers
- per-directory cache
- plugin runtime
- metrics and health endpoints

The daemon is the only component allowed to do slow prompt work.

### Protocol

The daemon protocol is length-prefixed JSON over `SOCK_STREAM`. See [RFC-0001](../rfcs/0001-daemon-wire-protocol.md).

The hot path is one request frame and one response frame per prompt render.

### Renderer

The renderer builds a configured module pipeline and composes ANSI prompt output. Modules declare one execution class:

- `sync`: bounded hot-path work only
- `async`: placeholder now, worker result later
- `cached`: read daemon-maintained state only

See [RFC-0002](../rfcs/0002-module-execution-classes.md).

### Cache

Shisa uses three cache layers:

- L1 rendered-prompt LRU keyed by render inputs plus `cache_rev`
- L2 module-output cache keyed by module and scope
- L3 external-command cache for off-path subprocess probes

Filesystem events, TTL expiry, env changes, and command-version changes invalidate cache entries. See [RFC-0004](../rfcs/0004-cache-invalidation-rules.md).

### Plugins

Core modules are Zig. Third-party plugins are Lua and must declare capabilities in `plugin.lua`. The daemon enforces capabilities on every host API call. See [RFC-0003](../rfcs/0003-lua-plugin-capability-manifest.md).

## Request Flow

1. Shell `preexec` records command start time.
2. Shell `precmd` captures exit status, jobs, duration, cwd, and terminal capabilities.
3. Shell hook sends a `render` request to `shisad`.
4. Daemon checks rendered-prompt L1.
5. Renderer reads sync/cached modules and schedules async misses.
6. Daemon returns prompt and optional `redraw_token`.
7. Async completions update cache and can trigger shell redraw.

## Failure Model

- Missing socket: auto-spawn daemon, then fallback if not ready.
- Daemon crash: supervisor restarts with backoff.
- Slow plugin: disable for session and report through `shisa doctor`.
- Watcher limit: fall back to TTL refresh and report degraded cache.
- Unsupported terminal capabilities: downgrade color and glyph output.

## Performance Contract

Warm render p99 target is under 2 ms. The prompt hot path must not spawn subprocesses, walk large directories, call network APIs, or wait on async workers.
