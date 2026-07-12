# Benchmark cross-reference

This is the shared reading of the committed Phase B ContinuityBench and Phase C standard-recall artifacts. It reports the harness's case-insensitive expected-substring score; it is not a model-judged leaderboard or a general product-performance claim.

## Phase B — ContinuityBench v0

| System | Stale rate | Contradiction accuracy | Mean retrieved tokens | Result against Shibahama |
| --- | ---: | ---: | ---: | --- |
| Shibahama | 0.375 | 1.000 | 10.620 | reference |
| Warehouse | 0.825 | 0.000 | 11.820 | Shibahama wins stale rate and token cost |
| Full context | 0.375 | 1.000 | 13.425 | ties stale and contradiction; Shibahama uses 2.805 fewer tokens |
| Mem0 OSS exact-event | 0.812 | 0.140 | 13.425 | Shibahama wins stale rate, contradiction accuracy, and token cost |
| Engram exact-event | 0.475 | 0.680 | 12.290 | Shibahama wins stale rate, contradiction accuracy, and token cost |

On ContinuityBench, Shibahama wins the stale-rate comparison against Warehouse, Mem0 OSS exact-event retrieval, and Engram; it ties full context at `0.375`. It has the lowest mean retrieval-token cost (`10.620`) of all five systems. The full-context tie prevents a blanket stale-answer superiority claim.

## Phase C — standard conversational recall

| Suite | System | Queries | Accuracy | Stale rate | Mean retrieved tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| LoCoMo | Full context | 1531 | 0.314 | 0.686 | 4095.105 |
| LoCoMo | Warehouse | 1531 | 0.153 | 0.847 | 90.816 |
| LoCoMo | Mem0 OSS exact-event | 1531 | 0.138 | 0.862 | 81.424 |
| LoCoMo | Shibahama | 1531 | 0.047 | 0.953 | 79.133 |
| LongMemEval-S | Full context | 500 | 0.500 | 0.500 | 74014.154 |
| LongMemEval-S | Warehouse | 500 | 0.422 | 0.578 | 11128.144 |
| LongMemEval-S | Mem0 OSS exact-event | 500 | 0.372 | 0.628 | 8758.462 |
| LongMemEval-S | Shibahama | 500 | 0.218 | 0.782 | 7481.056 |

Shibahama has no overall Phase C accuracy win or tie: `0.047` versus `0.314` for full context on LoCoMo, and `0.218` versus `0.500` on LongMemEval-S. Full context wins plain recall in both suites, while carrying `4095.105` and `74014.154` mean retrieved tokens respectively. Shibahama has the lowest reported token cost on both standard suites, but its corresponding stale rates are the highest (`0.953` and `0.782`).

Mem0 OSS exact-event retrieval exceeds Shibahama on the two standard-recall rows (`0.138` vs `0.047` on LoCoMo; `0.372` vs `0.218` on LongMemEval-S) and has lower stale rates in both. Shibahama uses `2.291` fewer mean tokens on LoCoMo and `1277.406` fewer on LongMemEval-S. On ContinuityBench, Shibahama instead has a `0.437` lower stale rate, `0.860` higher contradiction accuracy, and `2.805` fewer mean tokens than Mem0 OSS exact-event retrieval.

## Artifact provenance

| Artifact | Dataset SHA-256 | Scope |
| --- | --- | --- |
| `continuity/SUMMARY.md` | `a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa` (canonical JSON) | Phase B synthetic continuity slices |
| `phase-c-locomo.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` | 1,531 official LoCoMo-loader queries |
| `phase-c-longmemeval-s.json` | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` | 500 official LongMemEval-S-loader queries |

Reproduce the standard rows with the commands and loader metadata embedded in the two JSON artifacts. The external source paths are intentionally not treated as version-controlled datasets; their byte sizes and hashes are the reproducibility anchors.
