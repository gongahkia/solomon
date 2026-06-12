# Benchmarks

Benchmark harnesses and datasets for comparing Shibahama with long-horizon memory baselines.

## Local Harness

Run the deterministic local suite:

```bash
python benchmarks/run.py \
  --suite currencybench \
  --systems shibahama,warehouse \
  --output benchmarks/results/currencybench-local.json \
  --markdown benchmarks/results/currencybench-local.md
```

Supported suite names:

- `currencybench`: generated fact-change tasks.
- `coding-agent`: generated long-horizon coding-agent memory task.
- `locomo`: JSONL loader for LoCoMo-shaped task exports.
- `longmemeval`: JSONL loader for LongMemEval-shaped task exports.

Supported systems:

- `shibahama`: in-process Python binding with deterministic local embeddings.
- `warehouse`: append-only keyword baseline with no currency model.
- `mem0`: optional Mem0 OSS SDK adapter. Requires `mem0ai` plus its model/vector configuration.
- `zep`: optional Zep Cloud adapter. Requires `zep-cloud` and `ZEP_API_KEY`.

The harness reports recall accuracy, approximate retrieval token cost, p50/p95 query latency, and stale-answer rate. Missing external adapters can be recorded with `--allow-missing` so result tables clearly show which credentials or services were unavailable.

## Significance Variant Experiments

Compare transparent significance-function parameter variants offline:

```bash
python benchmarks/significance-variants.py \
  --output benchmarks/results/significance-variants.json \
  --markdown benchmarks/results/significance-variants.md
```

This script does not call any memory-system adapter. It mirrors the Rust
significance formula over deterministic synthetic histories, then ranks variants
by scenario so parameter changes can be reviewed before they are promoted into
benchmarked runtime behavior.

## Recall Latency Budget

The embedded hot-path budget is measured separately from adapter comparisons:

```bash
python benchmarks/recall-latency.py --check-budget
```

The default local budget is p50 <= 25 ms and p95 <= 75 ms for 1,000 memories, 200 measured queries, 16 dimensions, and top-k 5. The benchmark uses deterministic local embeddings, a temporary `redb` store, and the Python binding over the Rust core. Run without `--check-budget` to print a report without failing on timing.

## Embedded Memory-Footprint Budget

Measure resident memory growth for an embedded temporary store:

```bash
python benchmarks/memory-footprint.py --check-budget
```

The default local budget is RSS delta <= 128 MiB for 1,000 memories,
16-dimensional deterministic embeddings, capacity 1,000, and top-k 5. The
script reports resident-set delta and temporary database size as JSON. Run
without `--check-budget` to print the report without failing on the budget.
