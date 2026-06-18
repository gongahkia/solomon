# Supervisor

`shisa-supervisor` runs `shisad --foreground` and restarts it with capped exponential backoff after crashes.

It sends a `health` heartbeat to the daemon socket every 1s by default. Three missed heartbeats terminate and restart the daemon through the same backoff path.

The supervisor also leaves an active marker while running. If a service manager restarts the supervisor after three unclean supervisor exits within 60s, the next start writes a disabled marker and exits cleanly instead of looping.

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

Heartbeat interval override:

```sh
shisa-supervisor --heartbeat-ms 1000
```

Self-disable state reset:

```sh
shisa-supervisor --reset-disable
```

State defaults to `~/Library/Application Support/shisa/supervisor.state` on macOS and `$XDG_STATE_HOME/shisa/supervisor.state` or `~/.local/state/shisa/supervisor.state` on Linux. Override it for tests or custom service layouts:

```sh
shisa-supervisor --self-disable-state /path/to/supervisor.state
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
