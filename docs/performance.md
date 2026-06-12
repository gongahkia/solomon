# Performance Notes

## Recall Latency Budget

Use `python benchmarks/recall-latency.py --check-budget` to measure embedded recall latency. The
default local budget is p50 <= 25 ms and p95 <= 75 ms for 1,000 memories, 200 measured queries,
16-dimensional deterministic embeddings, and top-k 5.

This budget covers the in-process Rust core through the Python binding. It does not include hosted
embedding calls, external memory adapters, or network transport.

## Hot-Path Scan Boundary

Shibahama's recall path is intended to be lazy and id-bounded. A normal recall should:

1. Search the vector index for `top_k` candidate ids.
2. Read only those ids from storage with `get_many`.
3. Optionally expand through a related-memory provider by explicit related ids.
4. Record surfaced access events for returned candidates.

The recall hot path must not scan the full materialized store or event log. The regression test in
`core/src/retrieval.rs` guards against calls to known whole-store APIs from production recall
orchestration.

Whole-store scans are still allowed in administrative paths where the caller asks for aggregate
state, including server readiness, server inspection, export, snapshot, and tier-capacity
enforcement. Those paths must stay outside default recall.
