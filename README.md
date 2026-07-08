# Shisa

[![release reproducibility gate](https://github.com/gongahkia/shisa/actions/workflows/release.yml/badge.svg)](https://github.com/gongahkia/shisa/actions/workflows/release.yml)

A daemon-backed, async-first, cross-shell prompt that never blocks.

Shisa keeps slow prompt work out of the shell. A per-user daemon watches filesystem state, caches module output, and returns pre-rendered prompts over a Unix-domain socket on macOS/Linux or a named pipe on Windows so git status, language probes, and cloud context do not stall input.

## Status

**Alpha — works on a developer machine, not yet packaged.** The daemon (`shisad`) renders prompts over a local IPC endpoint; the `shisa prompt` client returns a composed prompt with async-fill placeholders for slow modules. Warm renders measured at 2–4 ms mean on macOS / Apple Silicon. There is no released artifact, no installer, and no signed binary yet — see [todo.md](todo.md) for what's still in the way.

Known gaps before a first release:
- Synthetic cold-big-repo CI is guarded; local nixpkgs and sparse Chromium numbers are recorded; full Chromium checkout numbers are still missing.
- Warm end-to-end p99 is guarded at 10 ms; the north-star <2 ms hot-path target still needs client/socket overhead work.
- `main.zig` split is partial (~4.4K lines remaining). Zig pre-1.0 churn risk concentrates here.
- Packaging (Homebrew / AUR / nixpkgs / scoop), code signing, and supply-chain attestation are not done.

To try it locally:

```sh
zig build
./zig-out/bin/shisad --foreground &
./zig-out/bin/shisa prompt --shell zsh --cwd "$PWD"
```

## Goals

- **Cold render in a real big repo without a timeout** — the falsifiable headline.
- Shell startup overhead under 5 ms.
- Warm prompt render p99 under 2 ms (upper bound; not the marketing claim).
- Cross-shell support for zsh, bash, fish, nushell, and PowerShell.
- Async, cached git and language probes.
- Capability-gated Lua plugins.
- Zero telemetry.

## Build flags

- `-Dvcs_extra=true` enables the `shisa stack` and `shisa worktrees` CLI verbs (hg / jj / sapling support). Default off. git is always on.
- AI helpers were removed from the core in phase 0; see [north-star §18](north-star.md) for the future opt-in pack spec.

## Quickstart

See [`docs/quickstart.md`](docs/quickstart.md) for the full first-run walkthrough. Local scaffold verification:

```sh
zig build test
zig build debug
zig build release
zig build bench
```

## Install

Arch AUR package recipes are staged under `packaging/aur/`:

```sh
yay -S shisa-bin
yay -S shisa-git
```

Nix packaging is staged under `packaging/nix/`:

```sh
nix-build -E 'let pkgs = import <nixpkgs> {}; in pkgs.callPackage ./packaging/nix {}'
nix build ./packaging/nix#default
nix-shell -p shisa
```

## Roadmap

The roadmap lives in [todo.md](todo.md). The product target lives in [north-star.md](north-star.md).

## License

MIT. See [LICENSE](LICENSE).
