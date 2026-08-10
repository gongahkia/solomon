# Socket Paths

Shisa uses one daemon socket per local user.

On Unix, after binding, the daemon explicitly sets the socket mode to `0600`.
`shisa doctor --only daemon/socket-permissions` reports a Unix socket whose
mode differs from that policy.

## Linux

Primary path:

```text
$XDG_RUNTIME_DIR/shisa.sock
```

Fallback when `XDG_RUNTIME_DIR` is unset:

```text
/run/user/<uid>/shisa.sock
```

The containing directory must be owned by the user and mode `0700`.

## macOS

Primary path:

```text
~/Library/Caches/shisa/shisa.sock
```

The daemon creates `~/Library/Caches/shisa` with mode `0700` when missing.

## Windows

Primary path:

```text
\\.\pipe\shisa-<sid>
```

`<sid>` is the current user's Windows SID, for example `S-1-5-21-...-1001`.

## Lock File

The single-instance lock sits next to the socket:

```text
<socket>.lock
```

The daemon must hold the lock before binding the socket.

## Cleanup

On graceful shutdown, the daemon unlinks the socket. On startup, it may remove a stale socket only after proving no live daemon owns the lock.
