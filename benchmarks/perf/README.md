<!-- SPDX-License-Identifier: Apache-2.0 -->

# Dependency propagation benchmark

The harness builds a direct authority-to-position fan-out and measures only the
`CurrencyPropagator.propagate_dependency_change` algorithm. It uses an in-memory store/graph fixture so 100k-item
algorithmic fan-out is measurable without SQLite journaling dominating the result. For its direct-fan-out topology,
the fixture discards each updated item after the propagation step; it verifies the affected-item count but does not
claim durable storage semantics. It also disables collection of the large per-item result-reasons payload,
verification-event creation, and per-item staleness metadata. This is a state-transition throughput benchmark, not an
audit-evidence benchmark. SQLite persistence and complete evidence creation are covered by normal test/performance
gates and should be benchmarked separately for deployment capacity planning.

Run the full 1k/10k/100k sweep locally:

```bash
uv run python benchmarks/perf/dependency_propagation.py
```

The CI regression check runs the 1k case with an explicit p95 budget. Run larger cases on controlled hardware before
changing the budget; do not compare absolute timings across runner types.
