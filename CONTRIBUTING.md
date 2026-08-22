# Contributing

Shisa's scope is defined by [north-star.md](north-star.md). Keep changes inside the target-contract boundary: make local command inputs more truthful and inspectable without activating contexts, handling credentials, or pretending to enforce remote policy.

Use Zig `0.15.2`.

```sh
zig fmt --check build.zig src/main.zig src/target.zig src/cli/target.zig
zig build test
zig build
zig build release
```

Add a focused test for every parser, source-precedence rule, or refusal boundary you change. Update [docs/target-contracts.md](docs/target-contracts.md) when the contract format or accepted executable set changes.
