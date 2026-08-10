# Shells

## Parity Matrix

| Shell | Init file | Prompt hook | Exit/jobs/duration | Async redraw handler | Transient prompt | Instant prompt | Integration test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zsh | `init/shisa.zsh` | `precmd` + `preexec` | yes | self-pipe `zle -F` + `zle reset-prompt` | yes | CLI supports `--instant`; hook does not enable by default | `test/integration/zsh_fake_socket.sh` |
| bash | `init/shisa.bash` | `PROMPT_COMMAND` + `DEBUG` trap | yes | `bind -x` on `\C-x\C-s` | best effort | CLI supports `--instant`; hook does not enable by default | `test/integration/bash_fake_socket.sh` |
| fish | `init/shisa.fish` | `fish_prompt` + `fish_preexec` | yes | `emit shisa_async_redraw` + `commandline -f repaint` | no | enabled by default via `--instant` | `test/integration/fish_fake_socket.sh` |
| nushell | `init/shisa.nu` | `$env.PROMPT_COMMAND` | exit/jobs yes; duration 0 | documented limitation | no | CLI supports `--instant`; hook off by default | `test/integration/nu_fake_socket.sh` |
| PowerShell | `init/shisa.ps1` | `prompt` | exit/jobs yes; duration 0 | `Register-EngineEvent` via `Shisa.AsyncFill`; host-limited | no | CLI supports `--instant`; hook off by default | `test/integration/pwsh_fake_socket.sh` |

The hooks provide shell-specific redraw handlers, but none of the checked-in hooks subscribes to daemon async-completion events or sends `render_continue` automatically. A Git or language-version cache miss is therefore visible as `[pending:<module>]` until a later prompt render; an external notifier may invoke the documented handler where the shell supports one.

## Version Compatibility Matrix

| Shell | Supported floor | Full feature floor | Current evidence | Drop rule |
| --- | --- | --- | --- | --- |
| zsh | 5.0; init returns without installing hooks below 5.0 | 5.0 plus `zsh/datetime` for duration | `test/integration/zsh_fake_socket.sh` when `zsh` is in PATH | update this table, changelog, release notes, and integration skip reason |
| bash | 3.x fallback prompt | 4.x for `PROMPT_COMMAND` + `DEBUG` trap + async key binding | `test/integration/bash_fake_socket.sh` plus Bash 3 fallback docs | update this table, changelog, release notes, and fallback behavior |
| fish | no hard version gate in init | version with `fish_prompt`, `fish_preexec`, `$CMD_DURATION`, and `commandline -f repaint` | `test/integration/fish_fake_socket.sh` when `fish` is in PATH | update this table, changelog, release notes, and integration skip reason |
| nushell | 0.113.x documented baseline | 0.113.x for `$env.PROMPT_COMMAND` and `job list` path | `test/integration/nu_fake_socket.sh` when `nu` is in PATH | update this table, changelog, release notes, and integration skip reason |
| PowerShell | `pwsh` host that can source `init/shisa.ps1` | host support for `Register-EngineEvent` if async repaint is desired | `test/integration/pwsh_fake_socket.sh` when `pwsh` is in PATH | update this table, changelog, release notes, and event-hook fallback |

Any shell-version drop must be documented here in the same change that updates init behavior or test coverage.

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

Set `SHISA_CMD_COMPLETE_BELL=1` before sourcing zsh, bash, or fish init to emit a completion notification after commands whose measured duration is at least `SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS` (default `10000`). `SHISA_CMD_COMPLETE_BELL_MODE` accepts `bell`, `osc9`, `notify-send`, or `macos`.

`shisa init --cmd-complete-bell --cmd-complete-bell-mode osc9 --cmd-complete-bell-threshold-ms 10000` writes these preferences to `shell.env` next to `shisa.toml`. The zsh, bash, and fish hooks read that file without sourcing it as shell code.

`shisa init --async off` writes `SHISA_ASYNC_FILL=0`; hooks then pass `--no-async` when rendering prompts. `--async on` writes `SHISA_ASYNC_FILL=1`, which keeps the default async fill behavior.

Set `SHISA_LONG_RUNNING=1` before sourcing zsh, bash, or fish init to print `shisa: command still running` after `SHISA_LONG_RUNNING_THRESHOLD_SECONDS` (default `30`) while a foreground command is still active. The default message does not include the command text.

`shisa prompt` emits OSC-7 cwd metadata before the rendered prompt so terminals that support it can open new tabs in the current directory. The sequence uses `file://<host><cwd>` and percent-encodes path bytes.

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

Command-aware context is opt-in through `[prompt]`. It is currently implemented in zsh only: Shisa debounces the ZLE command buffer, sends a context-only request to the daemon, and displays configured modules in `RPROMPT` (`command_context = "right"`) or the ZLE message area (`"message"`). Bash, fish, Nushell, and PowerShell retain their static prompt behavior.

## Graceful Degradation Matrix

| Condition | zsh | bash | fish | nushell | PowerShell |
| --- | --- | --- | --- | --- | --- |
| Daemon socket missing, instant off | `%~> ` fallback | cwd fallback | `prompt_pwd` fallback | `pwd` fallback | `Get-Location` fallback |
| Async redraw unavailable | external `USR1` notifications cannot repaint; a later prompt still uses the cache | no automatic repaint; bound key only works while Readline is active | no external repaint; a later prompt still uses the cache | no external parent-shell repaint; next `pre_prompt` consumes `shisa-reprompt` state | external event hook skipped if unsupported or disabled; a later prompt still uses the cache |
| Old shell or host | zsh 5.0+ documented | Bash 3.x uses sync `--no-async` prompt | fish hook path documented | Nushell 0.113.x tested baseline | `Register-EngineEvent` host support required for event delivery |

## zsh

- Requires zsh 5.0 or newer.
- Captures duration with `zsh/datetime` and `$EPOCHREALTIME`.
- Uses `%~> ` as fallback when the daemon socket is missing.
- Redraw handler is signal-driven: an external `USR1` notifier reaches `TRAPUSR1`, which writes to a self-pipe when available; `zle -F` drains it and calls `zle reset-prompt`.
- Transient prompt replaces accepted lines with `shisa prompt --transient` output when `transient_prompt` is configured.
- Shisa sets `PROMPT` and `RPROMPT`; `RPROMPT` calls `shisa prompt --right` and renders `[prompt].right_modules`.
- `command_context = "right"` appends configured context to `RPROMPT` while a matching command is being typed. `"message"` uses the ZLE message area instead. The hook never evaluates command text; quoted, piped, redirected, and compound commands are ignored.
- An externally triggered async redraw calls `zle reset-prompt`, so zsh recalculates both `PROMPT` and `RPROMPT`.
- If another plugin owns `RPROMPT`, source that plugin after Shisa if it should win.
- `SHISA_PROD_GUARD` is experimental and intentionally off by default.

## bash

- Requires Bash 4 or newer for the supported hook/redraw path.
- Bash 3.x falls back to a synchronous `PS1` command substitution that calls `shisa prompt --no-async`.
- Uses `PROMPT_COMMAND=shisa_prompt_command`.
- Preserves any existing `PROMPT_COMMAND` by evaluating it inside Shisa's prompt command.
- Captures duration with a `DEBUG` trap and `$EPOCHREALTIME`; Bash builds without `$EPOCHREALTIME` report `0ms`.
- Uses a Readline binding (`SHISA_ASYNC_KEYSEQ`, default `\C-x\C-s`) for async redraw.
- Bash redraw limitation: an external notifier must inject the bound key sequence into the active tty. Redraw only works while Readline is active, not while a foreground command is running.
- Bash has no native right prompt; set `SHISA_BASH_RIGHT_PROMPT=1` to draw `[prompt].right_modules` before `PS1` as a best-effort shim.
- Bash transient prompt is best effort: the DEBUG trap rewrites the previous single-line prompt before command execution in interactive Readline sessions. Multi-line prompts, wrapped commands, and ble.sh-managed accept-line flows are not rewritten.
- `SHISA_PROD_GUARD` is experimental and intentionally off by default.

## fish

- Uses `fish_prompt` and `prompt_pwd` fallback.
- Captures exit via `$status`, jobs via `jobs -p`, and duration via `$CMD_DURATION`.
- Enables `SHISA_INSTANT=1` by default, so cached prompts render before a daemon request.
- Defines `fish_right_prompt`, which calls `shisa prompt --right` and renders `[prompt].right_modules`.
- The redraw handler is fish-native: an external notifier can `emit shisa_async_redraw`, which calls `commandline -f repaint`.
- Shisa does not source or require `fish-async-prompt`. If that plugin is installed, keep its scheduling separate and emit `shisa_async_redraw` after Shisa async state changes.
- `SHISA_PROD_GUARD` is experimental and intentionally off by default.

## nushell

- Uses `$env.PROMPT_COMMAND` and a cwd fallback.
- Captures exit via `$env.LAST_EXIT_CODE` and jobs via `job list`; generic command duration is reported as `0ms`.
- Supported/tested baseline: Nushell 0.113.x.
- Sets `$env.PROMPT_COMMAND_RIGHT` to render `[prompt].right_modules`.
- Provides `shisa-reprompt`, which sets `SHISA_REPROMPT_REQUESTED=1`; a `pre_prompt` hook consumes it before the next prompt render.
- No reliable parent-shell repaint hook is available from an external process, so async redraw is documented as limited.

## PowerShell

- Uses a global `prompt` function and a cwd fallback.
- Captures native exit status and running PowerShell jobs; generic command duration is reported as `0ms`.
- Registers an externally raised `Shisa.AsyncFill` event with `Register-EngineEvent` when available; the action calls `Invoke-ShisaRedraw`.
- Defines `shisa_right_prompt_render` for hosts that compose their own right prompt; default `prompt` output remains left-only.
- Set `SHISA_PWSH_ASYNC_EVENT=0` before sourcing `init/shisa.ps1` to disable the event hook.

## Pending Shells
