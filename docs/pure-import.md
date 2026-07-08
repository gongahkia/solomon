# Pure Import

`shisa import-pure` takes no path and writes the smallest Pure-compatible Shisa config. Use `--dry-run` to print it instead.

Pure stores behavior in Zsh variables and `zstyle`, not a portable config file. The Shisa importer therefore emits a fixed preset based on Pure's default prompt behavior: https://raw.githubusercontent.com/sindresorhus/pure/main/readme.md

```toml
version = 1
theme = "pure"

[prompt]
modules = ["cwd", "git_branch", "exit_status", "cmd_duration", "jobs", "user_host"]

[modules.cmd_duration]
threshold_ms = 5000

[modules.user_host]
mode = "ssh"
```

Mapping:

| Pure behavior | Shisa target |
| --- | --- |
| Current directory | `cwd` |
| Git branch/status | `git_branch` |
| Non-zero exit indicator | `exit_status` |
| Command duration over 5 seconds | `cmd_duration` |
| Suspended jobs marker | `jobs` |
| User/host on SSH or container sessions | `user_host` |

No migration notes are emitted because there is no input file to partially translate.
