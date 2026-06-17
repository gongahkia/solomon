# Supervisor

`shisa-supervisor` runs `shisad --foreground` and restarts it with capped exponential backoff after crashes.

## Binary Install

`zig build` installs:

```text
zig-out/bin/shisa-supervisor
zig-out/bin/shisad
```

Packaged installs should place both binaries in the same directory. If they are split, pass the daemon path explicitly:

```sh
shisa-supervisor --daemon /path/to/shisad
```

## macOS LaunchAgent

User-level launchd plist path:

```text
~/Library/LaunchAgents/shisa.supervisor.plist
```

Recommended `ProgramArguments`:

```text
/path/to/shisa-supervisor
--daemon
/path/to/shisad
--socket
/Users/<user>/Library/Caches/shisa/shisa.sock
```

Daemon logs go to:

```text
~/Library/Logs/shisa/shisad.log
```

## Linux systemd User Unit

User unit path:

```text
~/.config/systemd/user/shisa-supervisor.service
```

Recommended `ExecStart`:

```text
%h/.local/bin/shisa-supervisor --daemon %h/.local/bin/shisad --socket %t/shisa.sock
```

Daemon logs go to `$XDG_STATE_HOME/shisa/shisad.log` when set, otherwise:

```text
~/.local/state/shisa/shisad.log
```

See [Socket Paths](socket-paths.md) for platform socket defaults.
