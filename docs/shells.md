# Shells

## Parity Matrix

| Shell | Init file | Prompt hook | Exit/jobs/duration | Async redraw | Transient prompt | Instant prompt | Integration test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zsh | `init/shisa.zsh` | `precmd` + `preexec` | yes | self-pipe `zle -F` + `zle reset-prompt` | yes | CLI supports `--instant`; hook does not enable by default | `test/integration/zsh_fake_socket.sh` |
| bash | `init/shisa.bash` | `PROMPT_COMMAND` + `DEBUG` trap | yes | `bind -x` on `\C-x\C-s` | no | CLI supports `--instant`; hook does not enable by default | `test/integration/bash_fake_socket.sh` |
| fish | `init/shisa.fish` | `fish_prompt` + `fish_preexec` | yes | `emit shisa_async_redraw` + `commandline -f repaint` | no | enabled by default via `--instant` | `test/integration/fish_fake_socket.sh` |
| nushell | `init/shisa.nu` | `$env.PROMPT_COMMAND` | exit/jobs yes; duration 0 | documented limitation | no | CLI supports `--instant`; hook off by default | `test/integration/nu_fake_socket.sh` |
| PowerShell | `init/shisa.ps1` | `prompt` | exit/jobs yes; duration 0 | `Register-EngineEvent` via `Shisa.AsyncFill`; host-limited | no | CLI supports `--instant`; hook off by default | `test/integration/pwsh_fake_socket.sh` |

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

Set `SHISA_CMD_COMPLETE_BELL=1` before sourcing zsh, bash, or fish init to emit a completion notification after commands whose measured duration is at least `SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS` (default `10000`). `SHISA_CMD_COMPLETE_BELL_MODE` accepts `bell`, `osc9`, `notify-send`, or `macos`.

`shisa prompt` emits OSC-7 cwd metadata before the rendered prompt so terminals that support it can open new tabs in the current directory. The sequence uses `file://<host><cwd>` and percent-encodes path bytes.

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

## Graceful Degradation Matrix

| Condition | zsh | bash | fish | nushell | PowerShell |
| --- | --- | --- | --- | --- | --- |
| Daemon socket missing, instant off | `%~> ` fallback | cwd fallback | `prompt_pwd` fallback | `pwd` fallback | `Get-Location` fallback |
| Async redraw unavailable | `TRAPUSR1` calls direct `zle reset-prompt`; non-ZLE contexts no-op | no automatic repaint; bound key only works while Readline is active | `emit shisa_async_redraw` calls `commandline -f repaint`; non-interactive contexts no-op | no external parent-shell repaint; next `pre_prompt` consumes `shisa-reprompt` state | event hook skipped if unsupported or disabled; `Invoke-ShisaAsyncFill` falls back to `Invoke-ShisaRedraw` |
| Old shell or host | zsh 5.0+ documented | Bash 3.x uses sync `--no-async` prompt | fish hook path documented | Nushell 0.113.x tested baseline | `Register-EngineEvent` host support required for event delivery |

## zsh

- Requires zsh 5.0 or newer.
- Captures duration with `zsh/datetime` and `$EPOCHREALTIME`.
- Uses `%~> ` as fallback when the daemon socket is missing.
- Redraw path is signal-driven: `TRAPUSR1` writes to a self-pipe when available; `zle -F` drains it and calls `zle reset-prompt`.
- Transient prompt replaces accepted lines with `%~> `.
- Shisa sets `PROMPT` and `RPROMPT`; `RPROMPT` calls `shisa prompt --right` and renders `[prompt].right_modules`.
- Async redraw calls `zle reset-prompt`, so zsh recalculates both `PROMPT` and `RPROMPT`.
- If another plugin owns `RPROMPT`, source that plugin after Shisa if it should win.
- When `SHISA_PROD_GUARD=1`, `preexec` sends `shisa cloud preexec --socket <socket> --shell zsh -- <command>` to the daemon.

## bash

- Requires Bash 4 or newer for the supported hook/redraw path.
- Bash 3.x falls back to a synchronous `PS1` command substitution that calls `shisa prompt --no-async`.
- Uses `PROMPT_COMMAND=shisa_prompt_command`.
- Preserves any existing `PROMPT_COMMAND` by evaluating it inside Shisa's prompt command.
- Captures duration with a `DEBUG` trap and `$EPOCHREALTIME`; Bash builds without `$EPOCHREALTIME` report `0ms`.
- Uses a Readline binding (`SHISA_ASYNC_KEYSEQ`, default `\C-x\C-s`) for async redraw.
- Bash redraw limitation: an external notifier must inject the bound key sequence into the active tty. Redraw only works while Readline is active, not while a foreground command is running.
- Bash has no native right prompt; set `SHISA_BASH_RIGHT_PROMPT=1` to draw `[prompt].right_modules` before `PS1` as a best-effort shim.
- When `SHISA_PROD_GUARD=1`, the `DEBUG` trap sends `shisa cloud preexec --socket <socket> --shell bash -- <command>` to the daemon.

## fish

- Uses `fish_prompt` and `prompt_pwd` fallback.
- Captures exit via `$status`, jobs via `jobs -p`, and duration via `$CMD_DURATION`.
- Enables `SHISA_INSTANT=1` by default, so cached prompts render before a daemon request.
- Defines `fish_right_prompt`, which calls `shisa prompt --right` and renders `[prompt].right_modules`.
- Redraw path is fish-native: handlers can `emit shisa_async_redraw`, which calls `commandline -f repaint`.
- Shisa does not source or require `fish-async-prompt`. If that plugin is installed, keep its scheduling separate and emit `shisa_async_redraw` after Shisa async state changes.
- When `SHISA_PROD_GUARD=1`, `fish_preexec` sends `shisa cloud preexec --socket <socket> --shell fish -- <command>` to the daemon.

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
- Registers `Shisa.AsyncFill` with `Register-EngineEvent` when available; the action calls `Invoke-ShisaRedraw`.
- Defines `shisa_right_prompt_render` for hosts that compose their own right prompt; default `prompt` output remains left-only.
- Set `SHISA_PWSH_ASYNC_EVENT=0` before sourcing `init/shisa.ps1` to disable the event hook.

## Pending Shells
