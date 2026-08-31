<!-- SPDX-License-Identifier: Apache-2.0 -->

# Benchmarks

Benchmark harnesses live here. The first target is recall plus currency-evaluation latency for the local
SQLite SKU, followed by propagation and impact-query scaling.

## Currency regression

Run:

```bash
uv run python benchmarks/currency_regression.py
```

The gate fails when Solomon stale-detection precision drops more than 5% below
`SOLOMON_BENCHMARK_PREVIOUS_PRECISION`, default `1.0`. Each run prints a manifest
with seed, version, environment, corpus size, supersession events, and changed
authorities.

Re-run from a prior result or manifest:

```bash
uv run python benchmarks/currency_regression.py --manifest benchmarks/results/2026-Q3.json
```

Generate a deterministic synthetic corpus:

```bash
uv run python benchmarks/synthetic/generate.py /tmp/solomon-corpus.json --size 12 --supersession-events 3 --seed 7
```

## Dependency propagation

Run the 1k, 10k, and 100k direct-fan-out benchmark:

```bash
uv run python benchmarks/perf/dependency_propagation.py
```

CI runs the 1k p95 regression gate; see [`perf/README.md`](./perf/README.md) for scope and larger-run guidance.
