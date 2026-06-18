# Shells

## Parity Matrix

| Shell | Init file | Prompt hook | Exit/jobs/duration | Async redraw | Transient prompt | Instant prompt | Integration test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zsh | `init/shisa.zsh` | `precmd` + `preexec` | yes | self-pipe `zle -F` + `zle reset-prompt` | yes | CLI supports `--instant`; hook does not enable by default | `test/integration/zsh_fake_socket.sh` |
| bash | `init/shisa.bash` | `PROMPT_COMMAND` + `DEBUG` trap | yes | `bind -x` on `\C-x\C-s` | no | CLI supports `--instant`; hook does not enable by default | `test/integration/bash_fake_socket.sh` |
| fish | `init/shisa.fish` | `fish_prompt` + `fish_preexec` | yes | `emit shisa_async_redraw` + `commandline -f repaint` | no | enabled by default via `--instant` | `test/integration/fish_fake_socket.sh` |
| nushell | `init/shisa.nu` | `$env.PROMPT_COMMAND` | exit/jobs yes; duration 0 | documented limitation | no | CLI supports `--instant`; hook off by default | `test/integration/nu_fake_socket.sh` |
| PowerShell | `init/shisa.ps1` | `prompt` | exit/jobs yes; duration 0 | `Invoke-ShisaRedraw`; external repaint limited | no | CLI supports `--instant`; hook off by default | `test/integration/pwsh_fake_socket.sh` |

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

`shisa prompt` emits OSC-7 cwd metadata before the rendered prompt so terminals that support it can open new tabs in the current directory. The sequence uses `file://<host><cwd>` and percent-encodes path bytes.

Set `SHISA_A11Y=1` before sourcing any init file to pass `prompt --a11y` from the hook.

## zsh

- Requires zsh 5.0 or newer.
- Captures duration with `zsh/datetime` and `$EPOCHREALTIME`.
- Uses `%~> ` as fallback when the daemon socket is missing.
- Redraw path is signal-driven: `TRAPUSR1` writes to a self-pipe when available; `zle -F` drains it and calls `zle reset-prompt`.
- Transient prompt replaces accepted lines with `%~> `.
- Shisa sets `PROMPT` only. It does not assign `RPS1`/`RPROMPT`; existing right prompts keep working after the init file is sourced.
- Async redraw calls `zle reset-prompt`, so zsh recalculates both `PROMPT` and `RPS1`/`RPROMPT` when those prompts contain substitutions.
- If another plugin owns `RPS1`, source that plugin before or after Shisa based on which plugin should define the right prompt; Shisa will not overwrite it.
- When `SHISA_PROD_GUARD=1`, `preexec` sends `shisa cloud preexec --socket <socket> --shell zsh -- <command>` to the daemon.

## bash

- Requires Bash 4 or newer for the supported hook/redraw path.
- Bash 3.x falls back to a synchronous `PS1` command substitution that calls `shisa prompt --no-async`.
- Uses `PROMPT_COMMAND=shisa_prompt_command`.
- Preserves any existing `PROMPT_COMMAND` by evaluating it inside Shisa's prompt command.
- Captures duration with a `DEBUG` trap and `$EPOCHREALTIME`; Bash builds without `$EPOCHREALTIME` report `0ms`.
- Uses a Readline binding (`SHISA_ASYNC_KEYSEQ`, default `\C-x\C-s`) for async redraw.
- Bash redraw limitation: an external notifier must inject the bound key sequence into the active tty. Redraw only works while Readline is active, not while a foreground command is running.
- When `SHISA_PROD_GUARD=1`, the `DEBUG` trap sends `shisa cloud preexec --socket <socket> --shell bash -- <command>` to the daemon.

## fish

- Uses `fish_prompt` and `prompt_pwd` fallback.
- Captures exit via `$status`, jobs via `jobs -p`, and duration via `$CMD_DURATION`.
- Enables `SHISA_INSTANT=1` by default, so cached prompts render before a daemon request.
- Redraw path is fish-native: handlers can `emit shisa_async_redraw`, which calls `commandline -f repaint`.
- Shisa does not source or require `fish-async-prompt`. If that plugin is installed, keep its scheduling separate and emit `shisa_async_redraw` after Shisa async state changes.
- When `SHISA_PROD_GUARD=1`, `fish_preexec` sends `shisa cloud preexec --socket <socket> --shell fish -- <command>` to the daemon.

## nushell

- Uses `$env.PROMPT_COMMAND` and a cwd fallback.
- Captures exit via `$env.LAST_EXIT_CODE` and jobs via `job list`; generic command duration is reported as `0ms`.
- Provides `shisa-reprompt`, which sets `SHISA_REPROMPT_REQUESTED=1`; a `pre_prompt` hook consumes it before the next prompt render.
- No reliable parent-shell repaint hook is available from an external process, so async redraw is documented as limited.

## PowerShell

- Uses a global `prompt` function and a cwd fallback.
- Captures native exit status and running PowerShell jobs; generic command duration is reported as `0ms`.
- Provides `Invoke-ShisaRedraw` to clear the current line, but external repaint is limited by host support.

## Pending Shells
