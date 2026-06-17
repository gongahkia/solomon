# CLI Keyboard Audit

Audit date: 2026-06-17.

Source check:

```sh
rg -n "termios|raw mode|ncurses|readline|interactive|readUntilDelimiter|readLine" src init docs
```

No raw-mode, full-screen, readline, or ncurses UI path is present in the current source tree. The only user confirmation prompt found in core CLI flow is `shisa plugin install` without `--yes`.

| Command | Keyboard-only status | Prompting behavior |
| --- | --- | --- |
| `ai` | args/stdout/stderr only | no interactive confirmation; generated commands are not executed |
| `bench` | args/stdout/stderr only | no prompt |
| `cache` | args/stdout/stderr only | no prompt |
| `cloud` | args/stdout/stderr only | no prompt |
| `doctor` | args/stdout/stderr only | no prompt |
| `explain` | args/stdout/stderr only | no prompt |
| `import-starship` | path arg/stdout | no prompt |
| `import-p10k` | path arg/stdout | no prompt |
| `import-oh-my-posh` | path arg/stdout | no prompt |
| `import-tide` | path arg/stdout | no prompt |
| `import-pure` | stdout only | no prompt |
| `init` | args/filesystem | no prompt |
| `pin` | path arg/filesystem | no prompt |
| `plugin install` | args/filesystem | y/N prompt unless `--yes` is passed |
| `plugin list` | stdout only | no prompt |
| `plugin enable` | plugin name arg/filesystem | no prompt |
| `plugin disable` | plugin name arg/filesystem | no prompt |
| `plugin trust` | plugin name arg/filesystem | no prompt |
| `prompt` | args/stdout | no prompt |
| `stack` | args/stdout | no prompt |
| `supervisor` | args/process control | no prompt |
| `vouch` | args/stdout/stderr | no prompt |
| `worktrees` | args/stdout | no prompt |

Any future full-screen, raw-mode, cursor-addressing, or persistent interactive UI must require an explicit `--interactive` flag.
