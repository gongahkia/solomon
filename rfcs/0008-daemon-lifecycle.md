# RFC-0008: Daemon Lifecycle Across SSH, Containers, nix-shell, tmux, sudo

- Status: Draft
- Created: 2026-06-23
- Owner: core maintainers
- Area: daemon lifecycle, hot-path failure modes

## Summary

Specifies how `shisad` behaves across the environment shapes that historically kill daemon-prompt projects: SSH, devcontainer / distrobox / toolbx, nix-shell, tmux session resume, sudo, multi-user hosts, and stale-socket recovery after a reboot. Until this RFC is accepted, no further request-handler growth lands in `src/daemon/server.zig`.

## Motivation

North-star §16 promotes daemon lifecycle to the top project risk. The 2020 starship daemon concept never shipped, in part because these environments are not single-host single-user happy-path. Shisa is a daemon-first prompt; if it cannot reason explicitly about each shape below, the fallback prompt becomes the only prompt many users see, and the project's headline (sub-30 ms in any size repo) is unprovable.

## Design

Each subsection specifies: (1) detection signal, (2) intended daemon model, (3) fallback if the model is unavailable, (4) cache/lifetime contract.

### 1. SSH-into-host

- **Detection:** non-empty `SSH_CONNECTION` plus `SSH_TTY`.
- **Model:** the daemon lives on the remote host. The local hook never reaches across the SSH connection. If `shisad` is installed on the remote, it auto-spawns per §29.2 against the remote user's `$XDG_RUNTIME_DIR` socket; if not installed, the hook prints a sync fallback prompt and emits a one-time install hint.
- **Forwarded sockets:** not in v1. Local-daemon-serving-remote-shell adds replay and credential-binding complexity without an obvious user win. Revisit in v2.
- **Cache contract:** remote daemon caches against remote paths. Hostname is part of the prompt-cache key indirectly via `cwd`; no extra keying needed.

### 2. Container nesting (devcontainer / distrobox / toolbx / podman exec / docker exec)

- **Detection:** existence of `/.dockerenv`, `/run/.containerenv`, or `CONTAINER` / `TOOLBX_PATH` env. Probed once per session in the hook, cached.
- **Model:** each container runs its own per-user `shisad` under the container's `$XDG_RUNTIME_DIR`. No bind-mounted host sockets. The cost (one extra ~25 MiB RSS per container session) is acceptable; the benefit (cache freshness for container-local paths, isolation from host capabilities) is high.
- **Fallback:** if the container image lacks the `shisad` binary, the hook prints a sync fallback prompt and surfaces a `shisa doctor` hint pointing at the install recipe for that image.
- **Cache contract:** caches are container-local. No cross-container cache sharing in v1.

### 3. nix-shell / devenv / flox

- **Detection:** `IN_NIX_SHELL` or `DEVENV_ROOT` or `FLOX_ENV` non-empty.
- **Model:** the host's user daemon serves the prompt. The daemon is **not** respawned per nix-shell — that would defeat caching. The daemon receives the active environment hash on each `render` and uses it as an extra dimension of the language-version cache key.
- **Cache poisoning:** PATH-flip without an fsnotify event is the failure mode. Mitigation: the shell hook computes a stable hash of `PATH` plus shell-managed env (`SHELL_PROFILE`, `NIX_PROFILES`) and sends it in the render request as `env_hash`. The daemon keys language-probe entries by `(cwd, env_hash)`. A new env_hash misses the cache and triggers a fresh probe. Stale entries are LRU-evicted as normal.
- **Fallback:** if `env_hash` is missing from a request (older hook), the daemon disables language-probe caching for that session and probes on every render. Loud warning via `shisa doctor`.

### 4. tmux session resume across daemon restarts

- **Detection:** `TMUX` non-empty.
- **Model:** tmux sessions outlive daemon restarts. The hook re-establishes the socket connection on every prompt regardless; long-lived FDs are not retained across renders (connection-per-request per RFC-0001). The only stateful surface across renders is the `session` UUID; if the daemon restarts, the new daemon sees a never-before-seen `session`, allocates new per-session state, and serves normally. No tmux-specific work in the daemon.
- **Cache contract:** unchanged. Tmux is transparent.

### 5. sudo and user impersonation

- **Detection:** `SUDO_USER` non-empty inside a shell.
- **Model:** when running as root via `sudo -i` or `sudo -s`, the hook connects to **root's** daemon under root's `$XDG_RUNTIME_DIR`, not the calling user's. This is the documented behavior and the only safe default — connecting to the calling user's daemon would cross a privilege boundary.
- **UX:** `shisa doctor` flags this with a single-line notice on first sudo'd render. Themes can render a `[root]` indicator (already covered by existing exit/jobs context).
- **Cache contract:** root has its own caches.

### 6. Multi-user hosts (single binary, many concurrent users)

- **Detection:** N/A; this is always-on behavior.
- **Model:** one `shisad` per user, enforced by `flock` on `$XDG_RUNTIME_DIR/shisa/socket.lock`. Sockets are 0700 per-user. No cross-user state.
- **System-level install:** the binary is shared (`/usr/local/bin/shisad`); per-user daemons spawn from it independently. No system daemon mode in v1.

### 7. Stale-socket recovery after reboot

- **Detection:** on auto-spawn, the hook finds an existing socket file but `connect()` fails with `ECONNREFUSED` or `ENOENT` on the lock file's holder PID.
- **Model:** the hook unlinks the stale socket, reacquires the lock, and respawns `shisad`. Race window protected by `flock`.
- **Fallback:** if the unlink-respawn cycle fails twice in a row within 5 s, the hook prints sync fallback and gives up auto-spawn for the session.

### 8. Crash mid-render

- **Detection:** supervisor heartbeat misses (§29.4) or hook receives EOF mid-frame.
- **Model:** the supervisor restarts `shisad` with exponential backoff (existing §29 contract). In-flight requests fail closed; the hook prints sync fallback for that prompt and retries on the next render.
- **Cache contract:** L1 (rendered-prompt) is in-memory and lost on restart; this is acceptable. L2 (module-output) is rehydrated from `~/.cache/shisa/cache.bin` if present.

## Boundary table

| Environment             | Daemon location       | Cache key extension      | Fallback              |
|-------------------------|-----------------------|--------------------------|-----------------------|
| SSH-into-host           | remote host           | (no extension; cwd-keyed)| sync prompt + hint    |
| Container               | inside container      | (no extension)           | sync prompt + hint    |
| nix-shell / devenv      | host user daemon      | `env_hash`               | sync probe per render |
| tmux                    | host user daemon      | none                     | none                  |
| sudo'd shell            | root daemon           | none                     | none                  |
| Multi-user host         | per-user daemons      | none                     | none                  |
| Post-reboot stale socket| respawned             | none                     | sync prompt           |
| Daemon crash            | supervisor-respawned  | L1 lost, L2 rehydrated   | sync prompt           |

## Performance

Each fallback path must still print a prompt in < 5 ms per north-star §6.6. Sync fallback uses the same renderer with `cached`-class modules disabled and `async`-class modules treated as `sync` with a 50 ms total budget. Beyond budget, the renderer emits a minimal `cwd $ ` prompt.

## Security

- All sockets remain 0700 per-user.
- The `env_hash` is a hash, not the raw PATH; no environment leaks across the wire.
- The container model deliberately rejects bind-mounted host sockets to prevent privilege crossover via container-escape.
- The sudo behavior is documented; no automatic privilege drop.

## Compatibility

- The shell hook gains an `env_hash` field in render requests. Daemons that don't understand it (older `v: 1`) ignore it per RFC-0001's "unknown fields are ignored" rule.
- No wire-protocol major version bump.

## Rejected Alternatives

- **Forwarded-socket SSH:** rejected for v1. Complexity > value.
- **Bind-mounted host socket in containers:** rejected. Crosses a security boundary for a minor cache-warmth win.
- **System-wide shisad service:** rejected for v1. Per-user is the unix norm for prompts; system service is in v2 scope (§45).
- **Polling for env changes instead of `env_hash` in the hook:** rejected. Polling is the kind of background work this project exists to avoid.

## Unresolved Questions

- What is the right scope of `env_hash`? PATH alone, or PATH + a small whitelist (`NIX_PROFILES`, `VIRTUAL_ENV`, `PYENV_ROOT`)? Decide before phase 2.
- Should `shisad --health` expose a per-environment summary so `shisa doctor` can render the table above with live status? Probably yes; tracked separately.
- How does `shisa --no-daemon` interact with each row above? Inherits the "sync prompt" column. Document in CLI reference when CLI lands.
