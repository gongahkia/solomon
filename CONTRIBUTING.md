# Contributing

Shisa is pre-MVP. Keep changes small, benchmark-aware, and tied to the roadmap in [todo.md](todo.md).

## Toolchain

- Zig: `0.16.0` from `build.zig.zon`
- Shell: zsh, bash, or fish for integration work
- OS targets: macOS and Linux

## Build

```sh
zig build debug
zig build release
```

## Test

```sh
zig fmt --check build.zig src
zig build test
zig build bench
```

Run the full local gate before opening a PR:

```sh
zig fmt --check build.zig src
zig build test
zig build debug
zig build release
zig build bench
```

## Benchmarks

Performance-sensitive changes must include benchmark evidence. The warm prompt render target is p99 under 2 ms. A warm-render regression over 10% blocks the change unless an RFC explicitly accepts the tradeoff.

## RFC Process

An RFC is required for changes to:

- wire protocol
- plugin API
- security model
- theme/rendering spec
- governance process

Use [rfcs/0000-template.md](rfcs/0000-template.md). RFCs must include rejected alternatives, compatibility impact, security impact, and performance impact.

Initial workflow:

1. Open an issue with the RFC proposal template.
2. Draft `rfcs/NNNN-short-title.md`.
3. Add it to [rfcs/README.md](rfcs/README.md).
4. Link the RFC from the PR.

## Pull Requests

Keep PRs scoped to one behavior or one doc task. Update [todo.md](todo.md) when completing roadmap work. Update docs when changing a user-facing flag, config field, module, or workflow.

## Conduct

All community spaces follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
