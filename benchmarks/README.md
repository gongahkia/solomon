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
