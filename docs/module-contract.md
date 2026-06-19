# Module Contract

Use this page before adding a core module, official plugin module, or official pack module.

## Required Evidence

Every new module change must include:

| Requirement | Evidence |
| --- | --- |
| Benchmark | `zig build bench`, a targeted benchmark from [Profiling Notes](profiling.md), or a written not-applicable reason when the module is outside the prompt hot path. |
| A11y label | A screen-reader label for every theme segment, module-exposed status, or diagnostic state that is rendered to users. |
| Glyph fallback | ASCII fallback text for every glyph or Unicode-only signal. If no glyph is added, state that explicitly in the PR. |

The warm-render p99 target remains under 2 ms. New sync work must be bounded; slow work belongs in an async module or daemon-owned cache.

## Core Modules

Core modules must update:

- `src/config.zig` for module id parsing, config schema exposure, defaults when enabled by default, and per-module options.
- `src/daemon/dispatcher.zig` for execution class, dispatch, placeholder behavior, and diagnostics naming.
- `docs/config-schema.md` when user-facing config changes.
- [Theme Spec](theme-spec.md) when a segment is added, renamed, or starts carrying glyphs.
- [Doctor](doctor.md) when the module introduces a new detectable failure mode.
- [Profiling Notes](profiling.md) or benchmark output when hot-path, cache, VCS, shell hook, or plugin-host behavior changes.

If a core module renders through built-in themes, each built-in segment definition must include `a11y`, and any non-empty `glyph` or `unicode` must include `ascii`. Existing theme tests cover those fields for built-in theme segment tables.

## Plugin And Pack Modules

Official plugin and pack modules must update:

- `plugin.lua` manifest `modules`.
- Declared capabilities for each filesystem, env, exec, network, or prompt access path.
- Authoring docs or pack docs when install or config behavior changes.
- Pack status and pack performance evidence when the module is part of an official pack.
- Threat-model docs when a new official pack, graduated pack, or capability expansion changes trust boundaries.

Third-party modules are validated by manifest and runtime capability checks, but official examples and templates must follow the same benchmark, a11y, and glyph fallback evidence rule.

## Review Gate

Reviewers should block a new module when any of these are missing:

- no benchmark evidence or not-applicable reason
- no screen-reader label for user-visible output
- glyph or Unicode-only status without an ASCII fallback
- new failure mode without `shisa doctor` coverage or a documented reason
- hot-path work that spawns subprocesses, walks unbounded directories, performs network I/O, or waits on slow plugin work
