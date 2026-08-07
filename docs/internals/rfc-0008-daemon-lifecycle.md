# RFC-0008 Internals: Daemon Lifecycle

RFC: [Daemon Lifecycle Across SSH, Containers, nix-shell, tmux, sudo](../../rfcs/0008-daemon-lifecycle.md)

## Decision

`shisad` lifecycle is defined per environment shape. Default model: one daemon per user, under the user's `$XDG_RUNTIME_DIR`, lock-file guarded. SSH-into-host runs a remote-side daemon (no socket forwarding in v1). Containers spawn per-container daemons (no host-socket bind-mount). nix-shell / devenv / flox uses the host daemon plus an `env_hash` cache-key dimension shipped in each `render` request. tmux is transparent. sudo connects to root's daemon (documented surprise). Stale sockets after reboot are unlinked-and-respawned under `flock`. Daemon crashes are restarted by the supervisor with exponential backoff.

## Why

Daemon-prompt projects historically die on lifecycle, not on render speed (north-star §16). The 2020 starship-daemon concept never shipped in part because no one specified what happens when the user `ssh`s into a remote host, `cd`s into a devcontainer, or enters a nix-shell that flips PATH without an fsnotify event. Shisa's headline depends on the daemon being available; the only way to keep it available across these shapes is to enumerate them and pick a contract per row.

## Implementation Notes

- The shell hook gains an `env_hash` field on `render` requests. RFC-0001's "unknown fields are ignored" rule makes this additive within wire-protocol `v: 1`. The hash covers `PATH` plus a small whitelist (open question, scoped before phase 2).
- Per-environment behavior table lives in the RFC itself (boundary table section).
- Sync-fallback budget: < 5 ms, `cached`-class modules disabled, `async`-class treated as `sync` with a 50 ms hard cap, then minimal `cwd $ ` if still over.
- Container detection (`/.dockerenv`, `/run/.containerenv`, `CONTAINER`, `TOOLBX_PATH`) is probed once per session and cached in the hook.
- SSH-into-host detection (`SSH_CONNECTION` + `SSH_TTY`) is used to suppress local auto-spawn; the remote daemon handles the render. No forwarded sockets in v1.
- sudo'd shells connect to root's daemon by socket-path resolution, not by leaking the calling user's runtime dir. This is the documented behavior; `shisa doctor` surfaces it on first sudo'd render.
- Crash recovery and supervisor heartbeat live in `src/supervisor.zig` (§29 of north-star).
- L1 rendered-prompt LRU is in-memory and lost on restart; L2 module-output cache rehydrates from `~/.cache/shisa/cache.bin` on warm-start.

## Executable acceptance coverage

`test/integration/lifecycle_acceptance.sh` verifies stale Unix-socket replacement, supervisor restart after an unclean daemon exit, and a tmux-shaped session rendering through the replacement daemon. `test/integration/nix_shell_language_version.sh` verifies the Nix environment-hash path when `nix-shell` is available. SSH, real containers, and sudo require their native user/host boundary and remain documented manual acceptance environments rather than being falsely represented by local environment variables.
