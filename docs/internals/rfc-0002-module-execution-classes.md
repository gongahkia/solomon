# RFC-0002 Internals: Module Execution Classes

RFC: [Module Execution Classes](../../rfcs/0002-module-execution-classes.md)

## Decision

Every prompt module is categorized as `sync`, `async`, or `cached`.

## Why

The renderer must preserve the warm prompt latency target even when VCS, language, cloud, or plugin probes are slow. Execution classes make blocking behavior explicit.

## Implementation Notes

- `sync` modules run on the render path and must avoid blocking I/O.
- `async` modules return stale or placeholder output and queue background work.
- `cached` modules read daemon-maintained state populated by watchers, timers, warmup, or workers.
- Placeholders still need accessibility labels so screen-reader output remains meaningful during refresh.
