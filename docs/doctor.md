# Doctor

`shisa doctor` prints local diagnostics:

- daemon socket path and health
- config directory status
- plugin directory status
- Lua runtime availability
- fsnotify backend
- active deprecations found in config
- Linux `fs.inotify.max_user_watches` when running on Linux

Use a non-default socket:

```sh
shisa doctor --socket /tmp/shisa.sock
```

Statuses:

| Status | Meaning |
| --- | --- |
| `present` | Path exists. |
| `missing` | Path does not exist. |
| `denied` | Path exists but is not accessible. |
| `unreachable` | Socket exists or was requested, but daemon health check failed. |
| `bad-response` | Daemon responded with unexpected health output. |
| `ok` | Daemon health check returned `ok`. |

Deprecation output is either `deprecations: none` or one line per deprecated interface in use.
