# Shells

## zsh

- Hook: `precmd` and `preexec`.
- Duration: `EPOCHREALTIME`.
- Async redraw: `TRAPUSR1` calls `zle reset-prompt`.
- Instant prompt: supported by `shisa prompt --instant`.

## bash

- Hook: `PROMPT_COMMAND`.
- Duration: `DEBUG` trap with `EPOCHREALTIME`; older Bash without `EPOCHREALTIME` reports `0ms`.
- Async redraw: Readline `bind -x` on `\C-x\C-s` runs `shisa_async_redraw`.
- Limitation: bash redraw needs an external notifier to inject the bound key sequence into the active tty; it only redraws while Readline is active, not while a foreground command is running.
- Instant prompt: uses the same `shisa prompt --instant` cache path, but the bash hook does not enable it by default.
