# Shisa

[![release reproducibility gate](https://github.com/gongahkia/shisa/actions/workflows/release.yml/badge.svg)](https://github.com/gongahkia/shisa/actions/workflows/release.yml)

The daemon-backed, async-first shell prompt.

Shisa keeps slow prompt work out of the shell. A per-user daemon watches local state, caches module output, and serves rendered prompts over a Unix socket on macOS/Linux or a named pipe on Windows.

## Status

**Alpha.** Shisa works from source on a developer machine. There is no signed release, Homebrew formula, Scoop manifest, or packaged installer yet.

Current release blockers:

- Full Chromium cold-render evidence is still missing.
- Warm end-to-end p99 is guarded at 10 ms; the north-star target remains under 2 ms.
- Packaging and release verification are not complete.

## Features

- Cross-shell prompt support for zsh, bash, fish, nushell, and PowerShell.
- Async git and language-version segments with daemon-side caching.
- Local context modules for cloud, IaC, SSH, containers, SSO, cost, VPN, and risk tier.
- Capability-gated Lua plugins.
- Starship, Powerlevel10k, Oh My Posh, Tide, and Pure migration helpers.
- `shisa doctor` for local diagnostics, repair hints, and machine-readable lint.
- Zero telemetry.

## Install From Source

Requirements:

- Zig `0.15.2`
- macOS, Linux, or Windows shell environment

```sh
git clone https://github.com/gongahkia/shisa.git
cd shisa
zig build release
```

For development:

```sh
zig build debug
zig build test
zig build bench
```

## Setup

Initialize config and install the hook:

```sh
./zig-out/bin/shisa init --defaults --shell zsh --theme nord-dark --async on --write-hook
```

Start the daemon:

```sh
./zig-out/bin/shisad --foreground &
exec zsh
```

Manual hook setup:

```sh
export SHISA_BIN=/path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.zsh
```

Use the matching file for other shells:

| Shell | Hook |
| --- | --- |
| zsh | `init/shisa.zsh` |
| bash | `init/shisa.bash` |
| fish | `init/shisa.fish` |
| nushell | `init/shisa.nu` |
| PowerShell | `init/shisa.ps1` |

## Configure

Shisa reads:

```text
~/.config/shisa/shisa.toml
```

Common commands:

```sh
shisa doctor
shisa doctor --json --severity-min warning
shisa doctor --list-checks
shisa explain
shisa font check
shisa theme preview nord-dark
```

Hide an active VPN segment by removing `"vpn_status"` from `[prompt].modules`.

## Troubleshooting

Doctor can isolate one subsystem:

```sh
shisa doctor --only daemon/not-running,daemon/socket-mismatch
shisa doctor --only modules/vpn-active,prompt/async-pending --severity-min info
shisa doctor --report /tmp/shisa-doctor.json --json --severity-min info
```

Expected first-run states:

- `shisad: another daemon already owns the socket lock`: a daemon is already running.
- `[pending:git_branch]`: async cache fill; render again.
- `vpn:Tailscale`: active VPN detected by `vpn_status`.
- skipped Pure or Nix tests: optional local prerequisites are missing.

See [docs/troubleshooting.md](docs/troubleshooting.md) and [docs/doctor.md](docs/doctor.md).

## Documentation

- [Quickstart](docs/quickstart.md)
- [Shell support](docs/shells.md)
- [Config schema](docs/config-schema.md)
- [Migrate from Starship](docs/migrate-from-starship.md)
- [Architecture](docs/architecture.md)
- [Roadmap](todo.md)
- [Product target](north-star.md)

## Build Flags

- `-Dvcs_extra=true` enables hg/jj/sapling stack and worktree CLI verbs. Default: off.
- AI helpers are not in core; future opt-in pack scope lives in [north-star section 18](north-star.md).

## License

MIT. See [LICENSE](LICENSE).
