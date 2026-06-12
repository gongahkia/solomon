# CurrencyBench

CurrencyBench is a small, deterministic benchmark for changed facts in
long-lived memory systems. It exists because generic recall accuracy does not
measure a common failure mode for agents: retrieving a fact that was once true
but has since been superseded.

The benchmark asks one question: when memory contains both an old fact and a
newer replacement, does the system return the current answer without leaking the
stale one?

## Motivation

Similarity-only memory stores can look good on static recall tasks while still
failing in active projects. Examples:

- an endpoint moved from `/api/v1/users/{id}` to `/api/v2/users/{id}`;
- production moved from `us-east-1` to `us-west-2`;
- ownership moved from one engineer to another;
- a feature flag was renamed after rollout.

All of these are easy to retrieve semantically. The hard part is currency:
knowing which observation is valid now.

## Task Shape

Each case has:

- one old observation, valid from Unix time `0`;
- one replacement observation, valid from Unix time `86400`;
- one query at Unix time `172800`;
- an expected current answer;
- a forbidden stale answer.

The deterministic v0 suite currently includes four cases:

| Case | Change | Expected | Forbidden |
| --- | --- | --- | --- |
| `billing-owner` | Billing ownership moved from Maya to Jules. | `Jules` | `Maya` |
| `api-route` | User lookup moved from v1 to v2. | `/api/v2/users/{id}` | `/api/v1/users/{id}` |
| `deploy-region` | Production region changed after a latency incident. | `us-west-2` | `us-east-1` |
| `feature-flag` | Checkout kill switch flag was renamed. | `checkout_halt_writes` | `checkout_disable_all` |

Cases are shuffled with a deterministic seed so systems cannot rely on fixed
ordering.

## JSONL Format

The external dataset format uses one benchmark case per line:

```json
{"name":"billing-owner","observations":[{"content":"The billing service owner is Maya.","valid_from_unix":0,"source_ref":"billing-owner:old"},{"content":"The billing service owner is Jules.","valid_from_unix":86400,"source_ref":"billing-owner:new","supersedes_source_ref":"billing-owner:old"}],"queries":[{"prompt":"Who owns the billing service?","expected":"Jules","forbidden":"Maya","now_unix":172800,"changed_at_unix":86400}]}
```

The harness loader also accepts this format for LoCoMo-shaped and
LongMemEval-shaped exports.

The checked-in v0 dataset is `benchmarks/currencybench/currencybench-v0.jsonl`.
Regenerate it with:

```sh
python benchmarks/currencybench/generate.py \
  --output benchmarks/currencybench/currencybench-v0.jsonl
```

## Metrics

CurrencyBench reports:

- `accuracy`: expected current answer appears and forbidden stale answer does
  not;
- `stale_answer_rate`: forbidden answer appears, or the expected answer is
  missing;
- `time_to_correction_seconds`: query time minus change time for correct
  answers;
- `retrieval_token_cost`: approximate whitespace-token count of returned memory
  context;
- `latency_p50_ms` and `latency_p95_ms`: wall-clock query latency in the
  harness.

## Running

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

Run the local Shibahama-vs-warehouse comparison:

```sh
python benchmarks/run.py \
  --suite currencybench \
  --systems shibahama,warehouse \
  --output benchmarks/results/currencybench-local.json \
  --markdown benchmarks/results/currencybench-local.md
```

Run from the checked-in JSONL dataset instead of the built-in generator:

```sh
python benchmarks/run.py \
  --suite currencybench \
  --dataset benchmarks/currencybench/currencybench-v0.jsonl \
  --systems shibahama,warehouse \
  --output benchmarks/results/currencybench-local.json \
  --markdown benchmarks/results/currencybench-local.md
```

## Current Local Result

The current checked-in local smoke result is:

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost |
| --- | --- | ---: | ---: | ---: | ---: |
| currencybench | shibahama | 12 | 1.000 | 0.000 | 5.917 |
| currencybench | warehouse | 12 | 0.000 | 1.000 | 11.833 |

Artifacts:

- `benchmarks/results/currencybench-local.json`
- `benchmarks/results/currencybench-local.md`

This is a local smoke result, not a hosted all-systems claim.

## Baseline Interpretation

The `warehouse` baseline is intentionally simple. It appends observations and
retrieves by keyword overlap, with no valid-time invalidation model. It should
surface the old facts in CurrencyBench because it has no way to know they were
superseded.

Shibahama's adapter invalidates the old observation when ingesting a replacement
with `supersedes_source_ref`, so default recall should return only the current
fact.

## Reproducibility Rules

When changing CurrencyBench:

- keep generated cases deterministic for a given seed;
- regenerate `currencybench-v0.jsonl` with `generate.py`;
- update this README if cases, metrics, or interpretation change;
- commit JSON and Markdown result artifacts together;
- do not expand the benchmark with private or unreleasable data;
- keep hosted-adapter credentials out of result files and logs.

## Citation

Repository citation metadata now lives in `CITATION.cff`, and Zenodo metadata
lives in `.zenodo.json`. Until a DOI is minted from a formal archived release,
cite this repository path and commit:

```text
CurrencyBench v0, Shibahama repository, benchmarks/currencybench, commit <commit>.
```

Include the exact result JSON used for any claim. See
`docs/launch/citable-submission.md` for the DOI submission checklist.
