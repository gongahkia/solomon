<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crash Consistency And Reconciliation Proof Protocol

## Locked decision

This protocol locks the next Solomon milestone. It addresses interruption between durable source documents,
knowledge and graph projections, currency propagation, and the metadata-only audit journal. It does not add a
parser rule, extraction semantic, automatic adjudication, mutable MCP action, or pilot activity.

The bounded claim to prove is:

> Solomon durably records multi-stage knowledge operations, survives interruption at defined persistence boundaries,
> detects incomplete projections, and resumes or reconciles them idempotently without creating unauthorized graph
> edges or losing audit provenance.

That is not a distributed-ACID claim. In particular, source documents remain SQLite-backed when the selected
knowledge/graph backend is PostgreSQL. A process interruption can therefore leave a durable source version without a
remote projection. The implementation must make that state detectable and repairable; it must not call it atomic.

## Observed starting state

This protocol is locked at `7f89b2999c3c8b7b1673a97e8055572351ba1d5c`, after the governed dependency assertion
proof. The worktree was clean before this protocol was written. The starting topology is established by
`SolomonService`, `create_storage_bundle`, the deployment configuration, and the existing stores:

| State | Current repository | Starting role |
| --- | --- | --- |
| Knowledge events/current state | SQLite default or PostgreSQL tenant schema | authoritative knowledge record |
| Dependency suggestions and edges | same selected SQLite file or PostgreSQL tenant schema | authoritative assertion and edge record |
| Retrieval index | same selected backend | rebuildable derived index |
| Source documents, versions, candidates, source changes | `sources.sqlite3` | authoritative evidence/version lineage |
| Authority sources and canonical identifiers | independent SQLite files | authoritative registration/canonicalization record |
| Authority event/task workflow | `workflow.sqlite3` | authoritative inbound-event/task state |
| Authority polling outbox | `authority-sources.sqlite3` | durable polling delivery record |
| Audit journal/audit packs | append-only JSONL | authoritative audit provenance, separate from databases |
| Retention and tenant/service-principal registries | atomically replaced JSON files | authoritative administrative state |

The local SKU deliberately uses SQLite WAL files for portable offline, single-writer operation. Server deployment
selects PostgreSQL for knowledge, graph, and pgvector retrieval through `SOLOMON_DATABASE_URL`; the production
Compose profile mounts both PostgreSQL and local `solomon-data`/`solomon-journal` volumes. Thus SQLite source content
is supported deployment state, not historical residue. The production CLI currently also requires explicit
backend wiring review because the API and console use the configured database URL while the local CLI constructor did
not pass it through at protocol lock.

Existing idempotency is local to individual workflows: knowledge outbox event identities, authority-event
`(source_id, idempotency_key)`, authority-poll events, governed assertion request digests, and one
`source_suggestion_id` edge index. Audit correlation IDs group records, but are not unique durable operation IDs and
cannot substitute for an operation journal.

Focused pre-change baseline:

```text
TMPDIR=/home/gongahkia/solomon-crash-consistency-baseline uv run pytest -q \
  tests/test_migrations.py tests/test_outbox.py tests/test_source_lifecycle.py \
  tests/test_filesystem_sync.py tests/test_governed_dependency_assertions.py tests/test_worker.py \
  tests/test_authority_polling.py tests/test_currency_loop_proof.py tests/test_audit.py \
  tests/test_audit_attribution.py tests/test_postgres_backend.py
# 46 passed in 10.69s
```

The governed assertion proof, its frozen parser baselines, and all prior audit artifacts remain immutable regression
evidence.

## Selected architecture

Adopt a backend-selected durable operation journal and idempotent projection worker. The journal is stored in the
selected knowledge/graph backend: it shares the local `solomon.sqlite3` database in SQLite-only use and the tenant
PostgreSQL schema in the PostgreSQL profile. PostgreSQL workers claim eligible rows using database row locking or a
conditional state transition; SQLite workers use a short `BEGIN IMMEDIATE` transaction and lease/version comparison,
never an in-process lock alone.

An operation is the durable, authorized request to perform a multi-stage transition. The operation's immutable
request and validated actor/scope context are authoritative for the requested transition; its graph, currency,
index, and audit effects are idempotent projections. It is intentionally not a generic workflow engine. The first
implemented operation types cover governed assertion creation/confirmation, source-revision reverification,
authority-change propagation, and their required audit completion. Existing source-change events remain the durable
SQLite-side marker for source writes. If a source write commits before its corresponding journal record, inspection
reports the missing operation and guarded reconciliation can materialize it from the reconstructible source event.

The worker offers at-least-once delivery of a projection attempt and exactly-once *semantic effects* where a database
constraint or deterministic idempotency key proves it: one edge per confirmed assertion, one staleness reason per
authority change, and one operation-attributed audit event per operation phase. It does not promise exactly-once
process execution or exactly-once network/database calls.

## Operation contract

Every operation includes an immutable UUID operation ID; operation type; tenant/matter/client scope; initiating
actor and authorization context summary; correlation and causation IDs; scoped idempotency key; source resource and
version; target; assertion/suggestion ID; requested transition; result IDs; and creation time. Mutable state includes
phase, validated state version, attempt count, lease owner/expiry, last successful checkpoint, safe failure category
and diagnostic, next eligible retry, terminal/recoverable status, update time, audit linkage, and repair-plan
version. Credentials, tokens, raw source content, raw evidence, and exception stack traces are excluded.

The permitted state table is `queued → claimed → queued|retrying|completed|terminal_failed|operator_required`;
`retrying → claimed|terminal_failed|operator_required`; and `claimed → queued|retrying|completed|terminal_failed|
operator_required`. Every creation, claim, checkpoint, retry, terminal result, and repair attempt appends immutable
history. Invalid transitions fail closed. Leases expire only after a bounded interval and a later worker records the
reclaim, so an uncleanly terminated worker does not strand an operation.

Retries use bounded exponential backoff with a fixed maximum attempt count. An exhausted or unsafe operation remains
visible as `terminal_failed` or `operator_required`; manual retry is accepted only after scope, authorization,
current-state, and operation-type validation. A retry never elevates a pending, rejected, deferred, withdrawn, or
expired assertion to an edge.

## Defined persistence boundaries and injected failures

Failure injection is test-only, disabled by default, and selected only by in-process test configuration or a
fixed subprocess environment variable consumed by the proof harness. It is not a REST, CLI, or MCP production
input. The implementation must name and exercise these points:

1. `before_authoritative_write` — rollback/no operation when the request was not durable.
2. `after_authoritative_write_before_schedule` — source-event reconciliation or operation resume.
3. `after_schedule_before_projection` — queued operation survives restart.
4. `during_graph_edge_projection` — retry without an unreviewed or duplicate edge.
5. `after_graph_edge_before_ack` — detect existing provenanced edge and harmlessly retry.
6. `during_currency_propagation` — resume idempotent change-ID propagation.
7. `after_currency_before_audit` — audit projection resumes exactly once by operation ID.
8. `during_source_revision_reverification` — source event and immutable document lineage remain recoverable.
9. `during_restart_retry` — expired lease becomes eligible and checkpoint resumes.
10. `during_concurrent_claim` — only one database claimant performs the active projection.

Tests distinguish rollback (one real database transaction aborts), safe retry (repeats an idempotent effect), resume
(continues from a stored checkpoint), reconciliation (detects and creates a missing safe projection), compensation
(not automatic for historical evidence/edges), and operator-required intervention (ambiguous, provenance-invalid,
cross-scope, or authorization-invalid state).

## Acceptance gates

The proof is all-or-nothing for: no silently lost confirmed operation; no edge for an unconfirmed assertion; no
duplicate edge/currency impact on duplicate delivery; deterministic restart convergence; concurrent claimant safety;
scoped inspection and repair; reconstructible evidence/version/audit lineage; dry-run non-mutation; stale-plan
refusal; no automatic repair of ambiguous/provenance-invalid state; real PostgreSQL/pgvector proof; actual
SQLite/PostgreSQL mixed proof; parser baseline preservation; and the repository's 90% coverage and release gates.

The deterministic two-scope scenario must deliberately create, detect, plan, repair, and recheck both a safe missing
projection and an unsafe ambiguous case. One run must `SIGKILL` only its bounded worker subprocess, then start a new
worker against the same on-disk/Persistent PostgreSQL state. Re-running its normalized semantic result must be byte
stable.

## Non-goals

No source content is copied into diagnostics; no human review is automated; no repair deletes history or performs
destructive compensation; no new distributed transaction coordinator is introduced; and MCP remains a scoped,
read-only inspection surface. A successful proof recommends only the following bounded milestone: production-profile
deployment, backup/restore and upgrade rehearsal, then an owner-operated pilot.
