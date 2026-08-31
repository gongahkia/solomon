<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crash Consistency And Reconciliation Proof Record

## Scope and topology

This proof exercises the supported mixed server profile: PostgreSQL with pgvector for knowledge, graph, retrieval,
and the durable operation journal; actual `sources.sqlite3` plus workflow/authority SQLite and audit JSONL under a
temporary local state root. It does not use a PostgreSQL fake or mock a cross-store write. The detailed model,
inventory, and decision are in the [consistency model](../consistency-model.md),
[operation matrix](../cross-boundary-operation-matrix.md), and [ADR 0010](../adr/0010-crash-consistency-reconciliation.md).

## Executed focused proof

The following passed against a disposable `pgvector/pgvector:pg16` instance with an isolated schema for each run:

```text
SOLOMON_TEST_POSTGRES_DSN=<local disposable DSN> \
  timeout 90s uv run pytest -vv -s tests/test_crash_consistency_proof.py
# 1 passed in 4.07s

SOLOMON_TEST_POSTGRES_DSN=<local disposable DSN> \
  SOLOMON_CRASH_DATABASE_URL=<same DSN> \
  uv run pytest -q tests/test_migrations.py tests/test_postgres_live_integration.py \
    tests/test_mixed_store_live_integration.py tests/test_crash_recovery_subprocess.py \
    tests/test_crash_consistency_proof.py
# 10 passed in 6.25s
```

The first test runs the scenario twice and compares normalized semantic output. It uses two scopes and covers normal
confirmation; queued recovery after an authoritative assertion write; edge-before-ack retry; currency retry; restart;
duplicate authority-change replay; two-worker claim contention; non-edge terminal decisions; source-revision
reconciliation; read-only inspection; dry-run, safe, stale, and cross-tenant repair outcomes; provenance-invalid
reporting; evidence hash/version reconstruction; audit linkage; and audit-pack verification. The subprocess test
uses `SIGKILL` at `after_graph_edge_before_ack`, so no ordinary exception cleanup participates in recovery.

Focused local interface and parser-regression coverage also passed before final release gates:

```text
uv run ruff check tests/test_cli.py tests/test_crash_consistency_proof.py
uv run pytest -q tests/test_cli.py tests/test_crash_consistency_proof.py
# 16 passed, 1 skipped in 7.35s
```

## Final verification and gate result

The final live-profile suite used the same disposable PostgreSQL instance and a writable temporary directory because
the host `/tmp` quota is consumed by unrelated artifacts:

```text
TMPDIR=<writable disposable directory> \
SOLOMON_TEST_POSTGRES_DSN=<local disposable DSN> \
SOLOMON_CRASH_DATABASE_URL=<same DSN> \
uv run pytest --cov
# 498 passed, 2 skipped (external model endpoints), in 169.76s
# coverage: 88.40%; configured 90.0% gate FAILED
```

This is a failed acceptance gate, not a waived result. No coverage exclusion, lowered threshold, or parser-baseline
change was made. The same live run passed the immutable reliance corpus (27 tests), real PostgreSQL migrations,
mixed-store recovery, the SIGKILL test, the headless two-run scenario, Helm validation, and Compose validation.

The final non-coverage gates passed: `ruff`, `mypy`, `mkdocs build --strict`, the aggregate
`scripts/release_quality_gates.py` (security, performance, restore, source review, MCP read-only checks),
`pip-audit`, source/wheel build, PyInstaller build, and the local binary smoke. This record deliberately does not
turn passing focused outcomes into a distributed-transaction claim or turn the failed coverage threshold into a pass.

## Failure classification proved

| Boundary result | Meaning in this proof |
| --- | --- |
| rollback | the named failure occurs before a database authoritative write and no operation is claimed as durable |
| safe retry | an already-applied edge/currency/audit phase is reread through its deterministic key/checkpoint |
| resume | a persisted operation lease/checkpoint becomes eligible after a restart |
| reconciliation | an authoritative source, item, assertion, or authority marker lacking its operation is rescheduled |
| repair | a separately planned, fingerprint-checked action restores only a valid confirmed assertion edge or source reverification |
| operator intervention | invalid provenance, duplicate/orphan edge, source lineage ambiguity, scope mismatch, audit corruption, or unsafe operation |

## Remaining limits

No cross-store ACID guarantee exists. Convergence depends on a running worker and its bounded retry policy; terminal
or operator-required records remain visible rather than disappearing. The local SQLite profile is single-writer, and
the durable profile deliberately refuses non-replayable on-demand LLM suggestion generation. These limits are part
of the public deployment and operations documentation, not hidden test assumptions.
