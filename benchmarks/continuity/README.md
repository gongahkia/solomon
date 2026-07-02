# ContinuityBench

ContinuityBench v0 is the Phase B dataset for mutable long-lived memory. It
extends CurrencyBench from 12 supersession-only smoke cases into a larger
synthetic continuity suite with four categories:

| Category | Tasks | Purpose |
| --- | ---: | --- |
| `supersession` | 80 | current fact must outrank stale fact |
| `contradiction` | 50 | higher-credence/provenance fact must win |
| `evidence-quality` | 40 | reported credence should track evidence strength |
| `stable-recall` | 30 | static recall control where flat retrieval can tie/win |

The domain split is 160 coding-agent tasks and 40 general tasks.

## Dataset

Files:

- `dataset/continuitybench-v0.json`
- `dataset/continuitybench-v0.sha256`

The JSON file contains `schema_version`, dataset metadata, and a `tasks` array.
Each task has:

- `task_id`, `category`, `domain`;
- ordered `events` with valid-time `t`, exact `content`, `provenance`,
  `establishes`, and optional `supersedes`;
- one `query` with query-time `t`, text, and `target_fact`;
- exact-match `answers` fields for current/stale or authoritative/rejected
  facts;
- category-specific `resolution` or `evidence` metadata where needed.

## Authorship

The v0 dataset is synthetic and templated in `generate.py`. It uses no private
data and no LLM-generated facts. The committed generator is the provenance record
for every task; generated records are intended for human review in code review.

## Regenerate

```sh
python3 benchmarks/continuity/generate.py
```

The hash file stores `sha256:<digest>` over canonical JSON (`sort_keys=True`,
compact separators) of the parsed dataset object. Result artifacts in
`benchmarks/results/continuity/` must carry this hash once item 31 lands.

## Scope

This commit is dataset design only. The system-agnostic ContinuityBench runner,
metric computation, baselines, and result artifacts are tracked by subsequent
Phase B items.
