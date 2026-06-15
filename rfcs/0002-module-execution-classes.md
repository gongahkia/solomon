# RFC-0002: Module Execution Classes

- Status: Accepted
- Created: 2026-06-15
- Owner: core maintainers
- Area: renderer

## Summary

Each prompt module declares exactly one execution class: `sync`, `async`, or `cached`. The renderer uses that class to decide whether a module may run on the hot path, must return a placeholder, or must read precomputed daemon state.

## Motivation

Shisa's main product claim is that prompt rendering does not block on slow probes. Execution classes make blocking behavior explicit and testable per module.

## Design

Module metadata includes:

```zig
const ExecutionClass = enum {
    sync,
    async,
    cached,
};
```

### `sync`

`sync` modules may run during `render`, but must not do blocking I/O or spawn subprocesses. Examples: exit status, job count, prompt character, and duration threshold formatting.

Rules:

- hard budget: 250 us per module in release builds
- no filesystem traversal
- no subprocess spawn
- no network
- no locks that can wait on worker completion

### `async`

`async` modules return a placeholder immediately during `render`. Work is queued to a daemon worker. Completion updates module cache and may trigger a shell redraw.

Examples: first git scan in a large repo, language version probes, cloud CLI probes, and optional AI pack calls.

Rules:

- render path returns placeholder or stale cache
- worker receives cwd, env snapshot, session, and cancellation token
- stale completions are discarded if cwd/session no longer match
- result includes an a11y string even for placeholder state

### `cached`

`cached` modules never compute during `render`. They read daemon-maintained cache populated by fsnotify, timer refresh, startup warmup, or async workers.

Examples: git dirty state after initial load, cloud context from config files, SSO expiry, and fully rendered prompt memoization.

Rules:

- cache lookup must be O(1) or bounded by small fixed lists
- cache miss returns placeholder or hidden segment
- invalidation increments `cache_rev`
- cache entries declare max age and watch scope

## Dispatcher

The renderer builds a module pipeline from resolved config. For each module:

1. `sync`: call render function.
2. `cached`: read cache and render state.
3. `async`: read cache; if stale or missing, enqueue worker and render placeholder.

The response `redraw_token` is non-null when any async module may later change the prompt.

## Performance

The combined warm render path must remain under 2 ms p99. The dispatcher records per-module elapsed time and logs slow sync modules. CI rejects warm-render regressions above 10%.

## Security

Execution class does not grant capabilities. A module still needs explicit capability permission for filesystem, env, exec, network, secrets, or pre-exec access.

## Compatibility

New classes require an RFC. Existing modules may move from `async` to `cached` only if behavior remains equivalent or strictly faster. Moving from `cached`/`async` to `sync` is a breaking performance change and needs benchmark evidence.

## Rejected Alternatives

- Single timeout knob: hides slowness instead of removing it.
- Every module async: adds redraw churn for trivial state.
- Runtime auto-classification: harder to reason about and weakens review.

## Unresolved Questions

- Exact release-build enforcement mechanism for per-module wall budgets.
- Whether plugin authors can declare multiple modes with daemon-selected fallback.
