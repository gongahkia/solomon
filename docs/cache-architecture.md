# Cache Architecture

Shisa's cache design is split between implemented daemon caches and the broader contract in [RFC-0004](../rfcs/0004-cache-invalidation-rules.md). This page documents current source behavior first, then the design targets that still need runtime wiring.

## Goals

- Prompt render should read memory or schedule async work, not wait on slow probes.
- Cache keys must include the shell state or module scope that changes output.
- Invalidation must be local, bounded, and explainable from filesystem events, TTL, or state changes.
- Stale async results must not replace newer results after `cd` or invalidation.

## Implemented Stores

### Generic module store

`src/daemon/cache.zig` defines the reusable `Store` used by cache-specific wrappers.

- Key shape: `module_id + NUL + cwd`.
- Value: duplicated output plus `cache_rev`, creation time, and last-access time.
- Defaults: `max_entries = 1024`, `max_age_ns = 5 minutes`.
- `put` replaces existing entries, then evicts expired entries and least-recently-used overflow.
- `get` returns a borrowed output slice and updates `last_access_ns`.
- `invalidate` removes one module/scope entry.

The store owns keys and outputs. Returned output is valid only until the store is mutated or deinitialized.

### Rendered prompt store

`src/daemon/prompt_cache.zig` wraps the generic store for rendered prompt strings.

The key is:

- cwd
- exit status
- job count
- command duration
- clock-enabled flag
- `--no-async` flag
- `cache_rev`

This is the intended L1 rendered-prompt cache from RFC-0004. Current server render code does not call this store; `Server.renderResponse` reads request state and calls `dispatcher.renderDefault` directly.

### Daemon-owned module caches

`Server` owns long-lived caches for:

- `git_branch`
- `language_versions`
- `cloud_ctx`

`dispatcher.renderDefault` receives those caches through `CacheSet`.

`git_branch` and `language_versions` use the same async shape:

- `mutex`
- `valid`
- `in_flight`
- `generation`
- `active_pid`
- `cwd`
- `segment`
- `worker`

On a hit, the cache duplicates the stored segment for the caller. On a miss, `renderAsync` returns `pending` and starts one worker. A second render for the same cwd while the worker is active also returns `pending`.

Changing cwd or invalidating the current cwd increments `generation`, kills the active child process when present, clears the cached segment, and detaches the worker for joining. Workers commit results only when their generation and cwd still match the cache state.

`cloud_ctx` caches local provider context by provider:

- GCP project keyed by Cloud SDK config path.
- Azure subscription keyed by `azureProfile.json`.
- Kubernetes context keyed by resolved kubeconfig path.

AWS profile is not cached in `cloud_ctx`; it is read from `AWS_PROFILE` or `~/.aws/config` during render.

### Local file caches

Some modules intentionally read local cache files and do not call network services from prompt render:

- `cost_glance` reads `~/.local/state/shisa/cost.json`.
- `iam_whoami` reads cached AWS STS, gcloud, and Azure identity JSON under `~/.cache/shisa`.
- `sso_expiry` reads AWS SSO token files and cached auth/session JSON.

These are data-source caches, not entries in `src/daemon/cache.zig`.

## Invalidation

### Filesystem scopes

`src/daemon/fsnotify.zig` stores debounced watch registrations. It selects a backend label from the OS (`fsevents`, `inotify`, or `unsupported`), owns registered paths, deduplicates by module/cwd, and emits invalidations after the scope debounce window.

`src/daemon/windows_fsnotify.zig` is a Windows POC for `ReadDirectoryChangesW`. It currently covers request planning, `FILE_NOTIFY_INFORMATION` parsing, and a Windows-only synchronous `ReadDirectoryChangesW` call wrapper. It is not wired into the daemon backend selector yet.

Current registered scopes:

- Git: `.git/HEAD`, `.git/index`, and the repository root recursively.
- GCP: `~/.config/gcloud` recursively.
- Azure: `~/.azure/azureProfile.json`.
- Kubernetes: resolved kubeconfig path.

`Server.renderResponse` drains pending invalidations before rendering, then registers git and cloud scopes for the current request. A filesystem invalidation clears matching daemon-owned caches.

### TTL and LRU

The generic store evicts by TTL and LRU during `put`; `get` also expires a stale entry before returning. The daemon-owned async caches do not use the generic TTL/LRU store in the current render path; they hold one cwd segment each.

### State keys

The rendered prompt cache key includes prompt state (`cwd`, `exit`, `jobs`, `duration_ms`, `time`, `no_async`) plus `cache_rev`. Module caches use module-specific scope keys such as cwd or provider config path.

### Generation checks

Async caches use `generation` as a stale-result guard. Invalidation or cwd change increments the generation. Worker completion compares its captured generation against the current generation before writing the segment.

## Request Flow

1. Shell hook sends a render request with cwd, exit status, job count, duration, terminal size, and capability hints.
2. Server drains pending filesystem invalidations.
3. Server registers watch scopes for the current git/cloud context.
4. Server reads environment inputs needed by modules.
5. Dispatcher renders sync modules and asks async modules for cached segments.
6. Async cache hit returns a segment; miss returns `[pending:<module>]` and a redraw token.
7. Worker completion fills the module cache for a later render.

## Observability

- `metrics` response includes live validity, in-flight state, generation, fsnotify backend, and registration count.
- `shisa cache stats` prints cache-shape defaults and zero entry counts; it does not query live daemon cache contents in the current CLI path.
- Slow module warnings log the first module in a render that exceeds the dispatcher threshold.

## Failure Modes

| Failure | Current behavior |
| --- | --- |
| Repeated cwd changes | Async caches cancel old work and reject stale worker results by generation. |
| Dirty repo churn | Git fs events debounce before cache invalidation. |
| Worker command hangs after invalidation | Active child PID is killed when known. |
| Watcher pressure | Linux inotify limits are counted and warned through daemon logs. |
| Unsupported fsnotify backend | Backend is reported as `unsupported`; render still works, but event-driven freshness depends on recorded events. |
| Cache growth | Generic store uses max entry count and TTL; daemon-owned async caches hold one segment per cache. |

## Current Gaps

- The rendered prompt cache is implemented and tested but not wired into `Server.renderResponse`.
- The reusable module-output `Store` is implemented and tested but the server currently relies on module-owned caches for git, language versions, and cloud context.
- RFC-0004's shared external-command L3 cache is a design target; current command results are folded into module-owned segments after async probes complete.
- `shisa pin` writes a pins file, but `src/daemon/cache.zig` eviction does not read pin state in current source.

Use [Profiling Notes](profiling.md) before changing these paths, and update RFC-0004 if a freshness rule changes.
