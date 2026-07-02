# ContinuityBench Summary

| System | Stale Rate | Contradiction Acc | Credence Rho | Credence n | Mean Tokens | Stable Acc | Where Baseline Beats Shibahama |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| shibahama | 0.375 | 1.000 | 1.000 | 40 | 10.620 | 1.000 | reference row |
| warehouse | 0.825 | 0.000 | n/a | 0 | 11.820 | 1.000 | none on headline metrics |
| full-context | 0.375 | 1.000 | n/a | 0 | 13.425 | 1.000 | none on headline metrics |
| mem0-oss-exact | 0.812 | 0.140 | n/a | 0 | 13.425 | 1.000 | none on headline metrics |
| engram-exact | 0.475 | 0.680 | n/a | 0 | 12.290 | 1.000 | none on headline metrics |

The comparison column lists strict baseline wins only; ties are visible in the metric columns.

Mem0 OSS is run as an exact-event retrieval baseline: `mem0ai` stores the dataset event text directly with `infer=False`, FastEmbed embeddings, and local Qdrant. This avoids hosted LLM/API-key extraction and isolates retrieval behavior.

Engram is run as an exact-event retrieval baseline with its offline `mock` LLM, `simple` embedder, and local Qdrant. It stores dataset event text directly with `infer=False`.

Full-context returns every event for the task, ranked by valid-time and corroboration for deterministic scoring; its token cost is the relevant baseline cost.
