# Benchmarks

Shibahama benchmarks are intended to measure whether a memory system can return
current, useful context over long horizons without excessive retrieval cost.
The harness lives under `benchmarks/` and writes both query-level JSON and
summary Markdown.

## Current Scope

The repository currently has deterministic local suites that can run without
hosted services. The local suites are the only results that should be treated as
reproducible from a fresh checkout today. LoCoMo and LongMemEval have official
dataset loaders, but checked-in result claims still require caller-supplied
dataset exports and committed run artifacts.

## Claim Boundary

The benchmark story is intentionally narrower than "beats flat retrieval on
every memory QA task." Recent memory-benchmark work shows that plain retrieval,
retrieval-stage tuning, or long context can be extremely strong on static
one-shot QA. See [`null-hypothesis.md`](null-hypothesis.md) for the full threat
model and citations.

Shibahama's home turf is continuity: facts that recur, change, become stale, or
need a visible reason why they should not be trusted. Result summaries should
therefore foreground stale-answer rate, retrieval token cost, time to correction,
and mutation/forgetting behavior before broad leaderboard accuracy. LoCoMo and
LongMemEval results must be reported alongside flat retrieval baselines, even
when those baselines win.

The closest published comparison to the bi-temporal, non-destructive part of the
thesis is Engram (`arXiv:2606.09900`). Any claim about supersession,
point-in-time recall, provenance-preserving invalidation, or token-efficient
LongMemEval-S retrieval must compare against Engram where the benchmark setup is
reproducible. Shibahama should lead with stale-rate, auditability, human signals,
and Tideline legibility only when those are measured or directly demonstrated.

## Systems

The harness uses a shared adapter interface with three operations: reset a case,
ingest observations, and answer a query from retrieved memory.

Current adapters:

- `shibahama`: in-process Python binding over the Rust core, with deterministic
  local embeddings from `benchmarks/shibahama_bench/embeddings.py`.
- `warehouse`: append-only keyword baseline with no currency or invalidation
  model.

There are intentionally no hosted/external-system adapters in the checked-in
registry. `benchmarks/shibahama_bench/adapters.py` validates adapter metadata at
import time; any future external adapter must declare checked-in successful
result artifacts before it can be used by the harness.

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
| currencybench | shibahama | 12 | 1.000 | 0.000 | 5.917 |
| currencybench | warehouse | 12 | 0.000 | 1.000 | 11.833 |

### ContinuityBench

ContinuityBench v0 is the larger Phase B dataset that extends CurrencyBench
beyond supersession-only smoke tests. It is committed at:

- `benchmarks/continuity/dataset/continuitybench-v0.json`
- `benchmarks/continuity/dataset/continuitybench-v0.sha256`

The dataset has 200 synthetic, templated tasks: 80 supersession, 50
contradiction, 40 evidence-quality, and 30 stable-recall controls. The domain
split is 160 coding-agent tasks and 40 general tasks. Its current canonical
dataset hash is
`sha256:a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa`.

The checked-in result files live under `benchmarks/results/continuity/`. The
current local summary is:

| System | Stale Rate | Contradiction Acc | Credence Rho | Credence n | Mean Tokens | Stable Acc |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| shibahama | 0.375 | 1.000 | 1.000 | 40 | 10.620 | 1.000 |
| warehouse | 0.825 | 0.000 | n/a | 0 | 11.820 | 1.000 |
| full-context | 0.375 | 1.000 | n/a | 0 | 13.425 | 1.000 |
| mem0-oss-exact | 0.812 | 0.140 | n/a | 0 | 13.425 | 1.000 |
| engram-exact | 0.475 | 0.680 | n/a | 0 | 12.290 | 1.000 |

Interpretation boundary: Mem0 OSS and Engram are exact-event retrieval
baselines here. They store the dataset event text directly with `infer=False`,
so this is a local retrieval/continuity slice, not a hosted extraction-quality
comparison. Shibahama ties full-context on stale rate and contradiction accuracy,
uses fewer returned tokens, and beats the exact-event Mem0/Engram baselines on
stale rate and contradiction accuracy for this slice.

### Coding-Agent Memory Task

`coding-agent` is a compact long-horizon coding-agent benchmark. It includes
project decisions, rejected approaches, superseded backlog ideas, and file
moves. It is a local continuity smoke, not an external-system comparison.

The checked-in result files are:

- `benchmarks/results/coding-agent-local.json`
- `benchmarks/results/coding-agent-local.md`

As of the current artifact, Shibahama scores `1.000` accuracy with `0.000`
stale-answer rate; the warehouse baseline scores `0.000` accuracy with `1.000`
stale-answer rate. Shibahama uses more retrieved tokens in this tiny fixture, so
the claim here is stale-rate behavior, not token efficiency.

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

`locomo` and `longmemeval` load the official JSON exports directly:

- LoCoMo: `locomo10.json` from `snap-research/locomo`, where generated
  session observations are used as memory observations and QA annotations become
  benchmark queries.
- LongMemEval: `longmemeval_s_cleaned.json`, `longmemeval_m_cleaned.json`, or
  `longmemeval_oracle.json` from `xiaowu0162/longmemeval-cleaned`, where each
  haystack session is stored as one timestamped memory observation.

They also retain support for the repo's neutral JSONL shape:

```json
{"name":"case-name","observations":[{"content":"...","valid_from_unix":0}],"queries":[{"prompt":"...","expected":"...","forbidden":null,"now_unix":0}]}
```

They are not bundled datasets. To run either suite, provide a dataset export
with `--dataset`. Result JSON records the dataset path, byte size, SHA-256, and
whether the suite used a built-in generator or an external file. Per-case
metadata also records whether the loader used the neutral JSONL shape, official
LoCoMo JSON, or official LongMemEval JSON.

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

Run the local coding-agent continuity smoke:

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

Run LoCoMo from the official export:

```sh
python benchmarks/run.py \
  --suite locomo \
  --dataset path/to/locomo10.json \
  --systems shibahama,warehouse \
  --output benchmarks/results/locomo-local.json \
  --markdown benchmarks/results/locomo-local.md
```

Run LongMemEval from the official cleaned export:

```sh
python benchmarks/run.py \
  --suite longmemeval \
  --dataset path/to/longmemeval_s_cleaned.json \
  --systems shibahama,warehouse \
  --output benchmarks/results/longmemeval-local.json \
  --markdown benchmarks/results/longmemeval-local.md
```

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
- include the command, suite, systems, top-k, seed, dataset path, dataset byte
  size, and dataset SHA-256 in the JSON config when an external dataset is used;
- keep generated local smoke results separate from hosted-service results;
- do not reuse placeholder labels for ablations unless the harness actually
  toggles significance, reconstruction, or graph behavior.

## External-System Gate

Do not add Mem0, Zep, hosted SaaS memory, or other external-system adapters as
missing-credential placeholders. A future external-system comparison must land
all of the following in one change:

- the adapter implementation and dependency instructions;
- the exact command and config used to run it;
- the generated JSON and Markdown result artifacts under `benchmarks/results/`;
- docs that scope the claim to the exact dataset, service version, model, seed,
  and credential setup.

Until then, README and launch materials must keep the claim to local Shibahama
versus warehouse-baseline runs.

The current Zep/Graphiti anchor status is explicitly not run:

- `benchmarks/results/zep-graphiti-not-run.json`
- `benchmarks/results/zep-graphiti-not-run.md`
