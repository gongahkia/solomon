# Shisa

[![release reproducibility gate](https://github.com/gongahkia/shisa/actions/workflows/release.yml/badge.svg)](https://github.com/gongahkia/shisa/actions/workflows/release.yml)

A daemon-backed, async-first, cross-shell prompt that never blocks.

Shisa keeps slow prompt work out of the shell. A per-user daemon watches filesystem state, caches module output, and returns pre-rendered prompts over a Unix-domain socket so git status, language probes, and cloud context do not stall input.

## Status

Shisa is pre-MVP. The repo currently contains the product spec, RFCs, build skeleton, and project scaffolding.

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

No usable release exists yet. For local scaffold verification:

```sh
zig build test
zig build debug
zig build release
zig build bench
```

## Roadmap

The roadmap lives in [todo.md](todo.md). The product target lives in [north-star.md](north-star.md).

## License

MIT. See [LICENSE](LICENSE).
