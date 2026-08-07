# RFC-0011: Right Prompt

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: shell integration, renderer

## Summary

Shisa should support an optional right prompt as a separate aesthetic slot. Right-prompt modules use the same module registry, async rules, cache invalidation, and capability model as the primary prompt. The initial user surface is:

```toml
[prompt]
modules = ["cwd", "git_branch", "exit_status"]
right_modules = ["cmd_duration", "time"]
right_format = "$cmd_duration $time"
```

and:

```sh
shisa prompt --side right
```

The default remains left-only.

## Motivation

Users migrating from Starship, Powerlevel10k, Tide, and Oh My Posh often use the right edge for secondary status: time, command duration, background jobs, or cloud context. Starship documents `right_format` for shells with a native right prompt, with bash requiring Ble.sh for full support. Shisa should support the same workflow without turning right prompt into a performance escape hatch.

For Shisa, right prompt is not primarily about moving slow work off the left side. Slow work is already async or cached. The value is layout: keep high-signal status visible without making the left prompt dense.

## Design

### Config

Add optional prompt keys:

```toml
[prompt]
right_modules = ["time", "cmd_duration"]
right_format = "$time $cmd_duration"
```

Rules:

- `right_modules` defaults to `[]`.
- `right_format` defaults to rendering `right_modules` in order with the active theme.
- Unknown module ids remain invalid.
- A module may appear on both sides only if explicitly listed on both sides.
- Right prompt inherits theme, glyph, ANSI, a11y, and RTL behavior from the primary render unless a future RFC adds side-specific styling.

### CLI

`shisa prompt` accepts:

```text
--side left|right|both
```

Behavior:

- `left`: current behavior; stdout is the primary prompt.
- `right`: stdout is only the right prompt.
- `both`: response contains both fields for shell hooks that can consume one daemon request.

The initial implementation may keep the daemon response shape as `prompt` plus `right_prompt: ?string`; this field already exists as `null` in the current prompt response. Older clients ignore it.

### Daemon Protocol

Render requests add:

```json
{
  "side": "left"
}
```

Allowed values: `left`, `right`, `both`. Missing means `left`.

Responses:

```json
{
  "prompt": "left prompt",
  "right_prompt": "right prompt or null"
}
```

Right prompt is fully rendered by the daemon. Shell hooks should not compose modules themselves.

### Async Interaction

Right modules participate in the same execution pipeline:

- `sync`: must meet the same sync budget.
- `cached`: reads daemon-maintained cache.
- `async`: returns placeholder or stale cache and sets the same redraw contract.

If left and right share a module result, the daemon should compute or read it once per request and reuse the value for both sides.

### Width Constraint

The daemon receives terminal columns in the render request. For `side=both`, it must ensure left plus right does not exceed the line width.

Recommended behavior:

1. Strip ANSI before measuring display width.
2. Reserve one cell between left and right.
3. If right prompt does not fit, truncate the right prompt first with an ellipsis.
4. If it still does not fit, return an empty right prompt.

Right prompt must be single-line. Newlines are stripped or rejected at config validation time.

### Shell Wiring

#### zsh

Use `RPROMPT`:

```zsh
RPROMPT="$("$SHISA_BIN" prompt --side right ...)"
```

Set `ZLE_RPROMPT_INDENT=0` in the generated hook to avoid trailing-space alignment surprises.

#### fish

Define `fish_right_prompt`:

```fish
function fish_right_prompt
    $SHISA_BIN prompt --side right ...
end
```

Fish has native right-prompt support, so this is the cleanest v1 path after zsh.

#### bash

Bash has no portable native right prompt. Support is limited:

- If Ble.sh is detected, use its right-prompt support.
- Otherwise degrade to left-only and expose a `shisa doctor` note.

Do not emulate RHS by cursor gymnastics in plain Readline for v1.

#### Nushell

Nu supports right prompt as a single-line prompt hook. Wire only the single-line case and document multiline limitations.

#### PowerShell

PowerShell has no direct equivalent in the current shell integration. Degrade gracefully to left-only.

## Performance

Primary prompt p99 must remain unchanged. `--side left` should not allocate or render right modules. `--side both` may do extra work, but all slow modules still follow async/cache rules.

Verification:

```sh
scripts/perf-suite.sh --repo /path/to/pinned-large-repo
```

No implementation should land if left-only p99 regresses beyond the existing gate.

## Security

Right prompt does not add host authority. It reuses the same module and plugin capabilities. A plugin cannot gain extra filesystem, process, network, or environment access by being rendered on the right side.

Shell hooks must quote command substitutions exactly as the existing prompt hook does. No right-prompt implementation may `eval` daemon output.

## Compatibility

The default config produces no right prompt. Existing configs keep working.

`right_prompt: null` is already part of the response shape, so clients can adopt it incrementally. Shells without right-prompt support degrade to left-only.

## Rejected Alternatives

- Treat right prompt as a Starship-compatible `right_format` parser only. This would duplicate config semantics instead of reusing Shisa modules.
- Use the fill module instead of native right-prompt hooks. Fill works for static one-line layouts but does not map well to shell-native RPROMPT behavior.
- Support bash RHS through manual cursor movement. It is fragile across Readline modes, wrapping, copy/paste, and screen readers.

## Unresolved Questions

- Whether `right_modules` should default to empty or migrate selected low-priority default modules there.
- Whether `--side both` should be the shell-hook default to reduce socket round trips.
- How to expose right-prompt diagnostics in `shisa doctor`.
- Whether side-specific themes are worth a later RFC.
