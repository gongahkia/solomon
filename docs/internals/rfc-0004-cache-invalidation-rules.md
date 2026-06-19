# RFC-0004 Internals: Cache Invalidation Rules

RFC: [Cache Invalidation Rules](../../rfcs/0004-cache-invalidation-rules.md)

## Decision

Cache-producing modules declare filesystem watches, environment inputs, command inputs, TTLs, and debounce windows that define cache validity.

## Why

Prompt rendering reads cache on the hot path. Invalidation rules keep cached output fresh without making every prompt rerun expensive probes.

## Implementation Notes

- Cache keys include module id, cwd or scope root, relevant env hash, command-version hash when applicable, and module schema version.
- Invalidation bumps a monotonic cache revision.
- Rendered prompt memoization includes cache revision so stale prompt strings naturally miss.
- Broad watches require debounce/backoff and should be avoided when exact files are enough.
