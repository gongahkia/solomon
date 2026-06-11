<!-- SPDX-License-Identifier: Apache-2.0 -->

# Benchmarks

Solomon's currency evaluation harness is intentionally small and reproducible. It generates synthetic
firm positions with explicit dependency edges, injects authority changes, and reports:

| Metric | Meaning |
|---|---|
| stale-surface rate | Fraction of returned items that are stale but surfaced as current. |
| time-to-flag | Seconds between dependency change ingestion and stale flag. |
| impact-query recall | Fraction of expected dependents found by `impact_query`. |

The harness includes a warehouse-style similarity baseline and a decay baseline to demonstrate why old is
not the same as stale.

```bash
uv run python -m solomon.evaluation
```

