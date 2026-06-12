# Benchmarks

Shibahama benchmarks are intended to measure whether a memory system can return
current, useful context over long horizons without excessive retrieval cost.
The harness lives under `benchmarks/` and writes both query-level JSON and
summary Markdown.

## Current Scope

The repository currently has two kinds of benchmark paths:

- deterministic local suites that can run without hosted services;
- adapter slots for external systems that require package installs, API keys, or
  model/vector configuration.

The local suites are the only results that should be treated as reproducible
from a fresh checkout today. LoCoMo, LongMemEval, Mem0, and Zep runs are wired
as harness targets but still require external datasets or service credentials.

## Systems

The harness uses a shared adapter interface with three operations: reset a case,
ingest observations, and answer a query from retrieved memory.

Current adapters:

- `shibahama`: in-process Python binding over the Rust core, with deterministic
  local embeddings from `benchmarks/shibahama_bench/embeddings.py`.
- `warehouse`: append-only keyword baseline with no currency or invalidation
  model.
- `mem0`: optional Mem0 OSS SDK adapter; requires `mem0ai` and its configured
  model/vector backend.
- `zep`: optional Zep Cloud adapter; requires `zep-cloud` and `ZEP_API_KEY`.

Use `--allow-missing` when running optional adapters in environments that may
not have credentials. Missing adapters are recorded as missing instead of being
silently omitted.

## Suites

### CurrencyBench

`currencybench` is a deterministic fact-change suite. Each case writes an old
fact, writes a newer fact that supersedes it, and queries after the change.

Metrics of interest:

- correctness: the answer contains the expected current value;
- stale-answer rate: the answer contains the forbidden old value or misses the
  expected value;
- time to correction: elapsed seconds from the fact change to the first correct
  answer;
- retrieval token cost: approximate whitespace-token count of returned memory
  text.

The current local smoke result is checked in at:

- `benchmarks/results/currencybench-local.json`
- `benchmarks/results/currencybench-local.md`

The checked-in summary is:

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost |
| --- | --- | ---: | ---: | ---: | ---: |
| currencybench | shibahama | 4 | 1.000 | 0.000 | 5.750 |
| currencybench | warehouse | 4 | 0.000 | 1.000 | 11.500 |

### Coding-Agent Memory Task

`coding-agent` is a compact long-horizon coding-agent benchmark. It includes
project decisions, rejected approaches, and file moves.

The checked-in result files are:

- `benchmarks/results/coding-agent-local.json`
- `benchmarks/results/coding-agent-local.md`

As of the current artifact, both Shibahama and the warehouse baseline score
`0.000` accuracy with `1.000` stale-answer rate on this benchmark. Treat that as
an open benchmark gap, not as a headline win. The separate
`examples/coding-agent/` demo covers the intended scenario behavior, but the
benchmark artifact should not be represented as passing until the harness result
does.

### Feature Ablation Suite

`ablation` is a deterministic local suite that isolates three Shibahama feature
families without placeholder labels:

- significance ranking: a reinforced project decision must beat a closer
  vector-only distractor;
- reconstruction/supersession: a newer fact must invalidate a stale owner fact;
- graph expansion: a vector anchor must pull in a related owner memory.

The checked-in result files are:

- `benchmarks/results/ablation-local.json`
- `benchmarks/results/ablation-local.md`

As of the current artifact, full Shibahama scores `1.000` accuracy and each
single-feature ablation scores `0.667`, failing only the case tied to its
disabled behavior.

### LoCoMo And LongMemEval

`locomo` and `longmemeval` are JSONL loaders for exported datasets with this
shape:

```json
{"name":"case-name","observations":[{"content":"...","valid_from_unix":0}],"queries":[{"prompt":"...","expected":"...","forbidden":null,"now_unix":0}]}
```

They are not bundled datasets. To run either suite, provide a dataset export
with `--dataset`.

## Running Local Benchmarks

Build the Python binding first:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip maturin
(
  cd bindings/python
  python -m maturin develop
)
```

Run the current local CurrencyBench comparison:

```sh
python benchmarks/run.py \
  --suite currencybench \
  --systems shibahama,warehouse \
  --output benchmarks/results/currencybench-local.json \
  --markdown benchmarks/results/currencybench-local.md
```

Run the coding-agent benchmark:

```sh
python benchmarks/run.py \
  --suite coding-agent \
  --systems shibahama,warehouse \
  --output benchmarks/results/coding-agent-local.json \
  --markdown benchmarks/results/coding-agent-local.md
```

Run the local feature ablations:

```sh
python benchmarks/run.py \
  --suite ablation \
  --systems shibahama,shibahama-no-significance,shibahama-no-reconstruction,shibahama-no-graph \
  --top-k 1 \
  --output benchmarks/results/ablation-local.json \
  --markdown benchmarks/results/ablation-local.md
```

Run a JSONL dataset export:

```sh
python benchmarks/run.py \
  --suite locomo \
  --dataset path/to/locomo-export.jsonl \
  --systems shibahama,warehouse \
  --output benchmarks/results/locomo-local.json \
  --markdown benchmarks/results/locomo-local.md
```

Swap `--suite longmemeval` for a LongMemEval-shaped JSONL export.

## Optional External Adapters

Mem0 requires the `mem0ai` package and whatever model/vector backend config the
SDK needs in the local environment:

```sh
python benchmarks/run.py \
  --suite currencybench \
  --systems shibahama,warehouse,mem0 \
  --allow-missing
```

Zep requires the `zep-cloud` package and `ZEP_API_KEY`:

```sh
ZEP_API_KEY=... python benchmarks/run.py \
  --suite currencybench \
  --systems shibahama,warehouse,zep \
  --allow-missing
```

Do not claim "all systems" results unless the generated JSON shows each adapter
with `"status": "ok"`.

## Metrics

Each query result records:

- `correct`: true when expected text appears and forbidden stale text does not;
- `stale_answer`: true when forbidden stale text appears or the expected text is
  absent;
- `latency_ms`: wall-clock query latency inside the harness;
- `retrieval_token_cost`: whitespace-token count of returned memory text;
- `time_to_correction_seconds`: query time minus fact-change time when the
  answer is correct after a change.

Summary rows group results by suite and system. They report accuracy,
stale-answer rate, mean token cost, mean correction lag, p50 latency, p95
latency, and adapter status.

## Recall Latency Budget

The recall latency budget is separate from cross-system benchmark comparisons.
It measures embedded Shibahama recall through the Python binding with a
temporary local store and deterministic embeddings.

Run:

```sh
python benchmarks/recall-latency.py --check-budget
```

Default parameters:

- 1,000 memories;
- 200 measured queries after 20 warmup queries;
- 16-dimensional deterministic embeddings;
- top-k 5;
- p50 budget <= 25 ms;
- p95 budget <= 75 ms.

Use `--output path/to/result.json` to preserve the measured latency report.

## Reproducibility Rules

When adding or updating benchmark results:

- commit the exact generated JSON and Markdown summary together;
- include the command, suite, systems, top-k, seed, and dataset path in the JSON
  config;
- keep generated local smoke results separate from hosted-service results;
- use `--allow-missing` only when a partial run is acceptable and the missing
  adapter rows are part of the output;
- do not reuse placeholder labels for ablations unless the harness actually
  toggles significance, reconstruction, or graph behavior.

## Open Benchmark Work

The TODO list still tracks benchmark work that is not complete:

- run LoCoMo through all systems after a dataset export and external service
  config are available;
- run LongMemEval through all systems after a dataset export and external
  service config are available;
- run Mem0 and Zep with real credentials/config for CurrencyBench.
