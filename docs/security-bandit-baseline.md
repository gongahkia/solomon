<!-- SPDX-License-Identifier: Apache-2.0 -->

# Bandit baseline

`.bandit-baseline.json` records the current Bandit findings reviewed on 2026-07-12. The baseline is intentionally
checked into source control so CI fails on new findings while retaining the existing findings for review.

All current findings are `B608` reports in SQLite/Postgres query builders. They interpolate internally constructed
SQL identifiers, placeholder lists, or clauses; query values are passed as database parameters. This is not a claim
that the code is permanently safe: changes to identifier/placeholder/clause construction require review, and any new
Bandit finding fails CI until explicitly assessed.

Run the scan locally:

```bash
uv run bandit -r src/solomon --baseline .bandit-baseline.json
```
