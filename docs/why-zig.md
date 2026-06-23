# Why Zig

Shisa's core is a long-running daemon plus a small CLI on the prompt hot path. The language choice optimizes for that shape, not for general application development.

## Decision

Core daemon, renderer, protocol, cache, and vetted modules are written in Zig. Third-party extension code is Lua through a capability-gated host API.

## Fit For Shisa

### Prompt latency is the product

The headline target is **cold render in a real big repo without a timeout** (north-star §10). Warm p99 under 2 ms is an upper bound on the hot path, not the marketing claim. The shell hook should package state, call the daemon socket, print the result, or print a fallback prompt.

Zig keeps the hot path in native code and lets the codebase keep allocation, subprocess, filesystem, and protocol work explicit. That matches Shisa's profiling rule: slow work moves to daemon caches or async workers, not shell hooks.

### Allocation boundaries are visible

The cache, protocol, plugin, and renderer code pass allocators through call sites. That makes ownership visible in review:

- cache stores duplicate owned keys and outputs
- prompt rendering returns owned strings
- tests can use `std.testing.allocator`
- plugin/runtime boundaries can fail closed on allocation or loading errors

This does not make memory bugs impossible. It makes allocation policy part of the API surface reviewers can inspect.

### The daemon is systems code

Shisa owns Unix-domain sockets, frame parsing, process spawning, signals, filesystem watching, and dynamic library loading. Zig is a direct fit for those OS boundaries without adding a second FFI layer for the core daemon.

Lua remains the plugin language because prompt extensions need ergonomics and a stable capability model more than access to daemon internals.

### Build and CI stay compact

The repo uses one `build.zig` for:

- debug binaries
- release binaries
- benchmark executable
- protocol schema generation
- generated docs
- unit and integration test wiring

`build.zig.zon` pins the minimum Zig version. CI installs Zig, formats, builds, tests, runs release builds, and runs benches through the same build graph.

### Distribution wants native binaries

The roadmap targets Homebrew, AUR, nixpkgs, WSL, and direct release archives. A native `shisa` plus `shisad` pair fits the install model and avoids requiring a language runtime in users' interactive shell startup path.

## Why Not Something Else

Rust was the closest alternative. It can fit the performance and distribution goals, but Shisa already depends on a tiny daemon core, explicit allocator review, and a Lua capability boundary. The current roadmap only mentions Rust as a future fallback wrapper, not the primary core.

Go would simplify daemon networking and concurrency, but it would put Shisa's core in a managed-runtime profile while the product spec calls out predictable allocations and small binaries as core reasons for the Zig choice.

Node, Python, Ruby, and shell are poor fits for the core because Shisa's prompt path should not depend on interpreter startup, package-manager state, or per-render subprocess work. They can still be useful for tooling around the project.

C and C++ fit the OS boundary but would add more manual memory and build-system surface than the current Zig build graph.

## Tradeoffs

Zig is pre-1.0. Language and standard-library churn can cost project time.

Mitigations already in the repo:

- `build.zig.zon` pins a minimum Zig version.
- CI checks formatting, debug/release builds, tests, docs generators, and benches.
- Core behavior is covered by Zig unit tests and integration scripts.
- Plugin behavior is kept behind Lua manifests and host capability gates, not exposed as arbitrary native plugins.

## Review Rule

Use Zig for code that is part of the daemon, protocol, renderer, cache, shell-facing CLI, or vetted core modules.

Use Lua for third-party prompt behavior that needs user customization and capability review.

Use shell only for hook glue and integration tests.

Do not add a new implementation language unless it removes a concrete maintenance or distribution cost.
