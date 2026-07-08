# Doctor

`shisa doctor` prints local diagnostics and hints for expected first-run states:

- daemon socket path and health
- default, environment, and owner socket details
- config directory status
- config directory permissions
- detected shell and terminal
- shell hook install status
- `SHISA_BIN` executable status
- transient prompt status
- Nerd Font detection status
- plugin directory status
- Lua runtime availability
- fsnotify backend
- active deprecations found in config
- Linux `fs.inotify.max_user_watches` when running on Linux
- active async placeholder and VPN segment hints

Use a non-default socket:

```sh
shisa doctor --socket /tmp/shisa.sock
```

Run read-only lint:

```sh
shisa doctor --lint
shisa doctor --lint --severity-min info
```

Emit machine-readable lint:

```sh
shisa doctor --lint --json
```

Apply available fixes interactively:

```sh
shisa doctor --fix
```

Apply all fixes without prompting:

```sh
shisa doctor --fix --yes
```

Fixable issues are annotated with `[fix available]`. Current fixes:

| Issue | Fix |
| --- | --- |
| Missing shell hook | Runs `shisa init --write-hook`, which appends an idempotent `# >>> shisa >>>` block to the current shell startup file. |
| Stale socket file | Removes the socket only after `lsof`/`fuser` reports no owner. |
| Daemon not running | Runs `shisad --daemonize`. |
| Config dir permissions | Runs `chmod 0700 <config_dir>`. |
| Nerd Font missing | Prints an install command only; it does not install packages. On macOS the command is `brew install --cask font-hack-nerd-font`. |

## Lint

`shisa doctor --lint` does not prompt, start daemons, remove sockets, or write files. It reports findings at `warning` and `error` severity by default.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | No findings at the selected severity. |
| `1` | Findings were reported. |
| `2` | Reserved for doctor runtime failures. |

Severity filter:

```sh
shisa doctor --lint --severity-min info
shisa doctor --lint --severity-min warning
shisa doctor --lint --severity-min error
```

JSON shape:

```json
{
  "status": "findings",
  "severity_min": "warning",
  "findings": [
    {
      "id": "daemon/not-running",
      "severity": "error",
      "message": "daemon is not reachable",
      "path": "/tmp/shisa.sock",
      "fix_hint": "start `shisad --foreground &` or run `shisa doctor --fix`"
    }
  ],
  "count": 1
}
```

Finding ids:

| Id | Severity | Meaning |
| --- | --- | --- |
| `config/unreadable` | error | Config could not be read. |
| `config/invalid` | error | Config failed schema validation. |
| `config/dir-permissions` | warning | Config directory permissions are too broad. |
| `daemon/not-running` | error | Target daemon socket is not reachable. |
| `daemon/stale-socket` | warning | Socket path exists but does not answer health checks. |
| `daemon/already-running` | info | Daemon is already healthy; a second default daemon will print `AlreadyRunning`. |
| `daemon/socket-mismatch` | warning | `SHISA_SOCKET` differs from the socket being checked. |
| `daemon/non-default-socket` | info | Doctor is checking an isolated/non-default socket. |
| `shell/hook-missing` | warning | Shell hook is not installed or active. |
| `shell/bin-missing` | error | `SHISA_BIN` is not executable. |
| `terminal/nerd-font` | warning | Nerd Font support was explicitly reported missing. |
| `terminal/unknown` | info | Terminal could not be identified. |
| `prompt/async-pending` | info | Prompt contains a normal first-render async placeholder. |
| `modules/vpn-active` | info | `vpn_status` is enabled and a VPN segment is active. |

Statuses:

| Status | Meaning |
| --- | --- |
| `present` | Path exists. |
| `missing` | Path does not exist. |
| `denied` | Path exists but is not accessible. |
| `unreachable` | Socket exists or was requested, but daemon health check failed. |
| `bad-response` | Daemon responded with unexpected health output. |
| `ok` | Daemon health check returned `ok`. |

`transient: on` means `transient_prompt` is configured and the shell hook is installed. `transient: config-only` means the config key exists but the current shell hook is missing.

Deprecation output is either `deprecations: none` or one line per deprecated interface in use.

## Adding Failure Modes

Any new user-visible failure mode must update `shisa doctor` in the same change unless the failure is impossible to detect locally.

Required review notes:

- failure symptom
- local signal `doctor` checks
- output status or warning text
- test or reason detection cannot be tested

Examples that should update `doctor`:

- new socket path or daemon health failure
- new config file location or permission rule
- new plugin runtime dependency
- new filesystem watcher backend or limit
- deprecated interface that can be detected from config
