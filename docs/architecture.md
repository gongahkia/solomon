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

It sends that state to the daemon over a Unix-domain socket and prints the returned prompt. The prompt client gives its daemon connection and request a 5 ms interactive deadline; when that attempt fails, it prints a minimal fallback prompt.

### Daemon

`shisad` owns:

- Unix-domain socket server
- render pipeline
- module scheduler
- filesystem watchers
- rendered-prompt L1 cache, module-owned async caches, and cloud-context caches
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

The user-facing `shisa.toml` schema is defined in [config-schema.md](config-schema.md).

### Cache

Shisa's cache contract is described in [RFC-0004](../rfcs/0004-cache-invalidation-rules.md) and the current source-level layout is detailed in [Cache Architecture](cache-architecture.md).

Current daemon code uses one cwd-scoped module-owned cache each for async Git and language probes, provider-specific cloud-context caches, and an active L1 rendered-prompt cache. The reusable generic module-output store and shared external-command cache remain design targets for the render path.

### Plugins

Core modules are Zig. Third-party plugins are Lua and must declare capabilities in `plugin.lua`. The daemon enforces capabilities on every host API call. See [RFC-0003](../rfcs/0003-lua-plugin-capability-manifest.md).

## Request Flow

1. Shell `preexec` records command start time.
2. Shell `precmd` captures exit status, jobs, duration, cwd, and terminal capabilities.
3. Shell hook sends a `render` request to `shisad`.
4. Daemon drains pending cache invalidations and registers current watch scopes.
5. Renderer reads configured modules, returning ready async cache values and scheduling cache misses.
6. Daemon returns prompt and optional `redraw_token`.
7. Async completions update module caches. The zsh hook starts a bounded background `render_continue` poll only when the daemon returns a redraw token, then uses its self-pipe to safely redraw the idle prompt once the cache is ready. Other hooks retain their documented next-render behavior.

## Failure Model

- Missing socket: auto-spawn daemon, then fallback if not ready.
- Daemon crash: supervisor restarts with backoff.
- Slow plugin: disable for session and report through `shisa doctor`.
- Watcher limit: fall back to conservative periodic invalidation and report degraded cache.
- Unsupported terminal capabilities: downgrade color and glyph output.

## Performance Contract

The falsifiable headline is **cold render in a real big repo without a timeout** (north-star §10). Warm render p99 under 2 ms is an upper bound on the hot path, not the marketing line — below ~10 ms is sub-perceptual to humans, and the cold-big-repo target is what users actually feel.

The prompt hot path must not spawn subprocesses, walk large directories, call network APIs, or wait on async workers. The daemon hot path imports no AI code (north-star §3 contract); `shisa ai` is not a CLI verb in the default build.

## Build flags

- `-Dvcs_extra=true` re-enables `shisa stack` and `shisa worktrees` plus the hg/jj/sl/stack/worktree test stanzas. Default off. git remains always-on.
