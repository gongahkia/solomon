# tmux pane

`tmux_pane` renders the current tmux pane id from the shell's `TMUX_PANE` environment variable.

Enable it by adding `tmux_pane` to the prompt pipeline:

```toml
[prompt]
modules = ["cwd", "tmux_pane", "git_branch"]
```

Rendered output:

```text
tmux:%3
```

Config:

```toml
[modules.tmux_pane]
enabled = true
```

Set `enabled = false` to suppress the segment without removing it from shared config.

The shell client sends `TMUX_PANE` with each prompt render request. The daemon does not query tmux or spawn `tmux`; outside tmux the segment is hidden.
