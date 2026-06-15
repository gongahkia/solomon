# RFC-0004: Cache Invalidation Rules

- Status: Accepted
- Created: 2026-06-15
- Owner: core maintainers
- Area: cache

## Summary

Modules declare the filesystem paths, environment inputs, command inputs, and time bounds that make their cached output valid. The daemon maps those declarations to fsnotify watchers, TTL refreshes, and cache revision bumps.

## Motivation

Shisa's renderer reads cache on the hot path. Cache entries must stay fresh without re-running expensive probes during prompt rendering.

## Design

Each cache-producing module declares:

```zig
const InvalidationScope = struct {
    fs_watch: []const WatchPath,
    env: []const []const u8,
    external_commands: []const CommandKey,
    max_age_ms: ?u64,
    debounce_ms: u64 = 50,
};
```

Cache keys include:

- module id
- cwd or declared scope root
- relevant environment snapshot hash
- declared external command version hash when applicable
- module schema version

Every invalidation increments monotonic `cache_rev`. Rendered-prompt L1 cache keys include `cache_rev`, so stale rendered prompts naturally miss.

## Filesystem Rules

Modules declare precise watch paths. Examples:

- git branch: `.git/HEAD`, `.git/packed-refs`
- git dirty state: `.git/index`, working-tree root, `.git/info/exclude`
- jj: `.jj/op_heads`
- kube context: every file named by `KUBECONFIG`, or `~/.kube/config`
- AWS profile: `~/.aws/config`, `~/.aws/credentials`

Watchers are recursive only when required by a module and allowed by platform limits. Broad watches must use debounce and backoff.

## Debounce

Multiple events for the same module/scope are collapsed into one invalidation within `debounce_ms`. The default is 50 ms. A module can request a larger debounce when its source produces event storms.

## TTL

`max_age_ms` is mandatory for state that can change without filesystem events, such as cloud API results or subprocess-derived versions. Expired entries are stale and must be refreshed by background workers.

## Environment Inputs

Modules list env vars that affect output. If any listed value changes between render requests for the same session, that module cache entry is invalidated for that session.

## External Command Inputs

If a module shells out off the hot path, cache validity includes the command path and version when known. Missing tools use negative cache entries with a TTL.

## Fallback

When fsnotify cannot be installed or watcher limits are exceeded:

- daemon logs a warning
- `shisa doctor` reports the degraded module/scope
- module falls back to TTL refresh
- prompt render remains non-blocking

## Performance

Invalidation must not walk large repos synchronously. Event handlers mark entries dirty and enqueue background refresh. L1 lookups remain O(1).

## Security

A plugin can only declare watches inside its `fs_watch` capability. Watch declarations are normalized before registration so symlink and `..` escapes do not broaden access.

## Compatibility

Changing a module's invalidation scope is user-visible if it affects freshness or watcher count. Such changes require tests covering stale-cache and event-refresh behavior.

## Rejected Alternatives

- Recompute every prompt: violates the core performance model.
- Pure TTL cache: stale for VCS and config changes.
- Watch entire home directory: too expensive and too broad for plugin safety.

## Unresolved Questions

- Platform-specific watcher limits for recursive git worktree watches.
- Whether persistent L2 cache should store the exact invalidation graph or rebuild it on daemon start.
