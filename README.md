# Shibahama

Shibahama is a usage-aware, reconstructive memory engine for LLM agents.

The current repository is an early implementation scaffold. The intended product is a Rust
core with Python and TypeScript/Node bindings, an optional server mode, benchmark harnesses,
and the Tideline visual debugger.

## Status

This project is pre-release. Core APIs and storage formats are expected to change until the
first public alpha.

Versions follow Semantic Versioning. Release notes are maintained in `CHANGELOG.md`.

## Repository Layout

- `core/`: Rust core library.
- `shibahama-cli/`: Rust command-line interface.
- `bindings/python/`: Python packaging and bindings.
- `bindings/node/`: Node.js packaging and bindings.
- `tideline/`: TypeScript/React visual debugger.
- `benchmarks/`: Evaluation harnesses and datasets.
- `examples/`: Runnable demos.
- `docs/`: Architecture notes and ADRs.

## Benchmark Snapshot

Current local CurrencyBench smoke result:

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost |
| --- | --- | ---: | ---: | ---: | ---: |
| currencybench | shibahama | 4 | 1.000 | 0.000 | 5.750 |
| currencybench | warehouse | 4 | 0.000 | 1.000 | 11.500 |

Full JSON and latency/correction-lag summary: `benchmarks/results/currencybench-local.json`.

## Development

Run the Rust gate locally:

```sh
scripts/ci/rust.sh
```

Run binding lane smoke checks:

```sh
scripts/ci/python-binding-smoke.sh
scripts/ci/node-binding-smoke.sh
```

Or enter the pinned Nix development shell:

```sh
nix develop
```
