# Refactor Baseline

Captured: 2026-07-10

Issue: #17 / W14 architecture refactor.

## Verification

Command:

```bash
uv run pytest --cov
```

Result:

- 189 passed
- 1 skipped (`SOLOMON_TEST_POSTGRES_DSN` not set)
- total coverage: 89%

## Largest Source Files

```text
11720 total
1130 src/solomon/api/service.py
 979 src/solomon/store/postgres.py
 795 src/solomon/mcp/tools.py
 726 src/solomon/evaluation.py
 585 src/solomon/console/app.py
 567 src/solomon/graph/suggestions.py
 496 src/solomon/api/app.py
 470 src/solomon/cli/main.py
 466 src/solomon/audit/journal.py
 393 src/solomon/orchestrator/retrieval.py
 388 src/solomon/store/sqlite.py
 374 src/solomon/graph/store.py
 369 src/solomon/boundary/engine/review.py
 314 src/solomon/orchestrator/models.py
 290 src/solomon/boundary/solomon.py
 241 src/solomon/mcp/schemas.py
 220 src/solomon/currency/engine.py
 217 src/solomon/mcp/server.py
 216 src/solomon/api/tenancy.py
 215 src/solomon/currency/prediction.py
 193 src/solomon/currency/models.py
 184 src/solomon/boundary/engine/client.py
 174 src/solomon/graph/visualization.py
 165 src/solomon/credence/policy.py
 154 src/solomon/boundary/engine/jurisdictions.py
```
