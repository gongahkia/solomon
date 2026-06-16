# Shells

## Parity Matrix

| Shell | Init file | Prompt hook | Exit/jobs/duration | Async redraw | Transient prompt | Instant prompt | Integration test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zsh | `init/shisa.zsh` | `precmd` + `preexec` | yes | `TRAPUSR1` + `zle reset-prompt` | yes | CLI supports `--instant`; hook does not enable by default | `test/integration/zsh_fake_socket.sh` |
| bash | `init/shisa.bash` | `PROMPT_COMMAND` + `DEBUG` trap | yes | `bind -x` on `\C-x\C-s` | no | CLI supports `--instant`; hook does not enable by default | `test/integration/bash_fake_socket.sh` |
| fish | `init/shisa.fish` | `fish_prompt` | yes | `emit shisa_async_redraw` + `commandline -f repaint` | no | enabled by default via `--instant` | `test/integration/fish_fake_socket.sh` |
| nushell | pending | pending | pending | pending | pending | pending | pending |
| powershell | pending | pending | pending | pending | pending | pending | pending |

## zsh

- Requires zsh 5.0 or newer.
- Captures duration with `zsh/datetime` and `$EPOCHREALTIME`.
- Uses `%~> ` as fallback when the daemon socket is missing.
- Redraw path is signal-driven: `TRAPUSR1` calls `zle reset-prompt`.
- Transient prompt replaces accepted lines with `%~> `.

## bash

- Uses `PROMPT_COMMAND=shisa_prompt_command`.
- Preserves any existing `PROMPT_COMMAND` by evaluating it inside Shisa's prompt command.
- Captures duration with a `DEBUG` trap and `$EPOCHREALTIME`; Bash builds without `$EPOCHREALTIME` report `0ms`.
- Uses a Readline binding (`SHISA_ASYNC_KEYSEQ`, default `\C-x\C-s`) for async redraw.
- Bash redraw limitation: an external notifier must inject the bound key sequence into the active tty. Redraw only works while Readline is active, not while a foreground command is running.

## fish

- Uses `fish_prompt` and `prompt_pwd` fallback.
- Captures exit via `$status`, jobs via `jobs -p`, and duration via `$CMD_DURATION`.
- Enables `SHISA_INSTANT=1` by default, so cached prompts render before a daemon request.
- Redraw path is fish-native: handlers can `emit shisa_async_redraw`, which calls `commandline -f repaint`.

## Pending Shells

- `nushell`: needs `init/shisa.nu`, prompt hook wiring, and documented redraw limits.
- `powershell`: needs `init/shisa.ps1`, prompt function wiring, and documented redraw limits.
