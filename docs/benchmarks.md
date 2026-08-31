<!-- SPDX-License-Identifier: Apache-2.0 -->

# Benchmarks

Solomon's benchmark suite is intentionally reproducible. It has three layers:

- a currency harness that generates firm positions with explicit dependency edges and injected authority
  changes;
- a jurisdiction coverage benchmark that exercises every vendored jurisdiction pack against expected boundary
  findings;
- an external-law monitoring fixture replay that diffs before/after authority snapshots and feeds detected
  changes into dependency propagation.

The currency harness reports:

| Metric | Meaning |
|---|---|
| stale-surface rate | Fraction of returned items that are stale but surfaced as current. |
| time-to-flag | Seconds between dependency change ingestion and stale flag. |
| impact-query recall | Fraction of expected dependents found by `impact_query`. |

The harness includes a warehouse-style similarity baseline and a decay baseline to demonstrate why old is
not the same as stale.

The jurisdiction coverage benchmark reports supported jurisdiction coverage, detector finding recall, and
failed case ids. The external-law monitoring benchmark reports change-detection recall, false-positive rate,
monitored jurisdictions, and downstream impact-query recall after detected fixture changes are propagated.

Retrieval ranking weights are calibrated by `tune_recall_weights()` against deterministic synthetic cases
covering exact relevance, firm-authoritative-vs-model-inferred tie breaking, and centrality tie breaking.
The selected profile is `similarity=0.70`, `credence=0.20`, `centrality=0.10`; CI tests assert that this
profile beats the similarity-heavy, credence-heavy, and centrality-heavy ablations in the calibration set.

```bash
uv run python -m solomon.evaluation
```
