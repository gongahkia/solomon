# RFC-0013: Reactive Prompt Updates

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: daemon lifecycle, shell integration

## Summary

Shisa should optionally redraw the current prompt when external state changes, without waiting for the user to press Enter. This is opt-in per module:

```toml
[modules.git_branch]
subscribe = true

[modules.cloud_ctx]
subscribe = true
```

The daemon debounces interesting invalidations and notifies the shell through the existing async redraw channel where possible. The first prototype target is zsh.

## Motivation

Today the prompt is refreshed when the shell requests a render: before a new prompt, after Enter, or during async-fill. That leaves visible stale state when another process changes the world:

- kubeconfig context switches in another terminal
- a Git rebase, merge, or checkout completes elsewhere
- direnv activates or reloads environment from a file watcher
- Terraform, Pulumi, or other workspace state changes

Shisa already owns fsnotify watchers and async redraw plumbing. Reactive updates extend that model from "async slot is ready" to "external state invalidated a subscribed module; re-render now if the line editor can safely repaint."

## Interesting State Changes

Initial eligible invalidations:

| Source | Signal | Module |
| --- | --- | --- |
| Git HEAD move | `.git/HEAD`, `packed-refs`, rebase/merge state files | `git_branch` |
| kubeconfig | `KUBECONFIG` files or `~/.kube/config` | future `kubectx` plugin / `cloud_ctx` |
| direnv | `.envrc`, `.direnv/`, exported activation marker | `language_versions`, future env-aware modules |
| IaC workspace | Terraform workspace files, Pulumi stack config | `iac_workspace` |

Modules opt in because not every invalidation should redraw a user's prompt. High-frequency sources such as working-tree dirty events remain cache invalidations only unless explicitly subscribed.

## Daemon Design

Each module may declare:

```zig
subscribe: bool = false,
subscribe_debounce_ms: u64 = 200,
```

When a watched path invalidates a subscribed module:

1. Mark the module cache stale as today.
2. Coalesce events by `(session, module, scope)` for at least 200 ms.
3. Emit one redraw notification to each subscribed session.
4. Drop notifications when a session has no active redraw channel.

Backpressure rules:

- hard minimum debounce: 200 ms
- max pending redraw notifications per session: 1
- if an update arrives while one is pending, merge it
- if a shell does not ack or re-render within the timeout, drop the notification

The daemon must never enqueue unbounded per-event work. File event storms become one redraw.

## Shell Redraw Mechanisms

### zsh

Supported first.

Mechanism:

- Extend `SHISA_ASYNC_FD` FIFO protocol with distinct bytes:
  - `A`: async slot ready
  - `R`: external subscribed state changed
- ZLE handler drains the FIFO.
- On `R`, call `zle reset-prompt` and `zle -R`.

Constraints:

- Works only while ZLE is active.
- Do not interrupt foreground commands.
- Multiline prompt cursor movement remains best effort.

### fish

Supported after zsh.

Mechanism:

- Use a background event or FIFO watcher.
- On redraw event, call `commandline -f repaint`.

Constraints:

- Repaint is reliable at the prompt.
- Foreground commands still block.

### bash

Limited.

Readline can redraw only while it owns the terminal. Plain bash has no robust async prompt repaint primitive comparable to ZLE. Ble.sh may provide a better path, but v1 should document bash as best-effort and may leave reactive redraw disabled by default.

### Nushell

Nu prompt customization is function-based through `PROMPT_COMMAND` and `PROMPT_COMMAND_RIGHT`. Public issues around repaint/transient behavior show that prompt repaint control is not equivalent to zsh ZLE. The first implementation should document Nu as unsupported for external redraw until a stable line-editor repaint hook exists.

### PowerShell

PowerShell prompt functions run when PowerShell asks for a prompt. There is no direct portable async repaint hook. Reactive updates should be disabled and documented as unsupported.

## Protocol

No wire-protocol change is required for the zsh prototype if the FIFO byte is enough. A later bidirectional subscription stream may use the existing `subscribe` daemon op:

```json
{
  "v": 1,
  "op": "subscribe",
  "topics": ["prompt.redraw"]
}
```

The subscription model is intentionally not a general pubsub layer in this RFC. It is scoped to prompt redraw hints.

## Config

Per-module opt-in:

```toml
[modules.git_branch]
subscribe = true
subscribe_debounce_ms = 250
```

Global kill switch:

```toml
[prompt]
reactive_updates = false
```

Defaults:

- `reactive_updates = false`
- module `subscribe = false`
- minimum debounce = 200 ms

This makes the feature opt-in and avoids surprising redraws for users who prefer stable prompts.

## Performance

Disabled path cost is zero except config parsing. Enabled path cost is paid on invalidation, not on every render.

Render path p99 must remain unchanged:

```sh
scripts/perf-suite.sh --repo /path/to/pinned-large-repo
```

Invalidation storms must be tested with at least 50 filesystem events per second and must produce no more than five redraw attempts per second per session at the 200 ms debounce floor.

## Security

Reactive redraw does not grant new module access. It only asks the shell to request a fresh render.

Risks:

- terminal spoofing through unexpected redraws
- cursor disruption while the user is typing
- denial of service from event storms

Mitigations:

- opt-in per module
- debounce and pending-event merge
- no redraw during foreground command
- shell-specific support matrix

## Compatibility

Existing configs and shell hooks are unchanged. New hooks must tolerate old daemons that only send the original async byte. Old hooks ignore unknown bytes by draining or treating them as generic redraw requests.

## Rejected Alternatives

- General daemon pubsub: broader than needed and would require stable topic semantics.
- Redraw on every fsnotify event: too noisy and likely to disrupt typing.
- Plain-bash cursor gymnastics: fragile and inaccessible.
- Foreground-command interruption: explicitly out of scope.

## Unresolved Questions

- Whether redraw subscriptions should be per shell session or per daemon connection.
- Whether plugin modules may declare subscription defaults in their manifest.
- Whether `direnv` should be represented by file watchers, an activation marker, or a shell hook field.
- Whether redraw acks are necessary or simple drop-on-next-render is enough.
