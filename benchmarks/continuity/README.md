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

The metric scorer accepts a system-output JSON file with ranked contexts:

```json
{
  "system": "adapter-name",
  "model": "none",
  "seed": 0,
  "tokenizer": "reported-by-adapter",
  "results": [
    {
      "task_id": "stable-recall-0001",
      "contexts": ["ranked memory text"],
      "item_credences": [0.9],
      "token_count": 4
    }
  ]
}
```

Score it with:

```sh
python3 benchmarks/continuity/score.py \
  --system-output path/to/system-output.json \
  --output benchmarks/results/continuity/adapter.json \
  --markdown benchmarks/results/continuity/adapter.md
```

Implemented metrics:

- stale-answer rate over supersession tasks, using the Phase B ranked-context
  rule;
- contradiction-resolution accuracy over contradiction tasks;
- Spearman rho for reported credence vs evidence-strength ordinal;
- mean retrieval token cost from adapter-reported token counts;
- stable-recall accuracy for the control category.

Baseline adapters, external systems, and checked-in result artifacts are tracked
by subsequent Phase B items.

Run the checked-in baseline set:

```sh
python3 benchmarks/continuity/run_baselines.py \
  --systems shibahama,warehouse,full-context,mem0-oss-exact,engram-exact \
  --output-dir benchmarks/results/continuity
```

The Mem0 OSS baseline requires `mem0ai` and `fastembed` installed in the Python
environment running the script. It stores exact dataset event text with
`infer=False`; this is a retrieval baseline, not a hosted LLM extraction run.

The Engram baseline requires `engram-memory` installed. It uses Engram's offline
`mock` LLM and `simple` embedder, stores exact dataset event text with
`infer=False`, and disables EchoMem, rerank/category/echo boosts for
deterministic local scoring.
