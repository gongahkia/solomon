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
- `ablation`: generated feature-isolation tasks for significance,
  reconstruction/supersession, and graph expansion.
- `locomo`: official `locomo10.json` loader, plus the neutral JSONL format.
- `longmemeval`: official cleaned LongMemEval JSON loader, plus the neutral
  JSONL format.

Supported systems:

- `shibahama`: in-process Python binding with deterministic local embeddings.
- `shibahama-no-significance`: Shibahama with significance removed from recall ranking.
- `shibahama-no-reconstruction`: Shibahama with supersession invalidation disabled.
- `shibahama-no-graph`: Shibahama with related-memory graph expansion disabled.
- `warehouse`: append-only keyword baseline with no currency model.

The harness reports recall accuracy, approximate retrieval token cost, p50/p95
query latency, and stale-answer rate. External-system adapters should only be
added when they have reproducible successful runs, not missing-credential
placeholders. The adapter registry validates this metadata at import time, so a
future hosted adapter must declare checked-in result artifacts before it can be
used by the harness.

## Interpreting Results

The expected Shibahama win condition is continuity, not every static recall
leaderboard. Flat retrieval and long-context baselines may win on one-shot QA,
especially when the relevant history is small enough to search or place in
context. Treat CurrencyBench stale-answer rate, token cost, and time to
correction as the primary local metrics. Treat LoCoMo and LongMemEval results as
valid only when the official exports and raw run artifacts are present. Runs with
`--dataset` record the dataset path, byte size, SHA-256, and loader format so the
artifact can be audited later. Report flat-retrieval baselines honestly even when
they are better.

## Feature Ablations

Run the local feature-isolation suite:

```bash
python benchmarks/run.py \
  --suite ablation \
  --systems shibahama,shibahama-no-significance,shibahama-no-reconstruction,shibahama-no-graph \
  --top-k 1 \
  --output benchmarks/results/ablation-local.json \
  --markdown benchmarks/results/ablation-local.md
```

The ablation suite has one targeted case per feature:

- significance ranking: a reinforced decision must outrank a closer vector-only distractor;
- reconstruction/supersession: a newer fact must invalidate the stale owner fact;
- graph expansion: a vector anchor must pull in a related owner memory.

The checked-in `ablation-local` result records full Shibahama at 3/3 accuracy,
while each disabled variant drops on the case tied to the removed behavior.

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

## Significance Recompute Profile

Profile the end-to-end `why()` path over one memory with a long access history:

```bash
python benchmarks/significance-recompute.py --check-budget
```

The default local guardrail is p95 <= 20 ms for 1,000 access events and 200
measured `why()` calls. This profiles the public binding path while exercising
the Rust significance explanation over the stored access history.

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
