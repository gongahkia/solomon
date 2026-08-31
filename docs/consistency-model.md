<!-- SPDX-License-Identifier: Apache-2.0 -->

# Consistency Model By Deployment Profile

## Shared terms

An **authoritative record** establishes a fact that later projections may derive from. A **projection** is a
rebuildable or repeatable view/effect. A journaled operation is durable before its multi-store effects begin. A
projection is delivered at least once; it has exactly-once semantic effect only where its idempotency key and storage
invariant prove that result. A checkpoint is durable only after the phase it records is observable on reread.

Operation ordering is per operation, not global. A worker may process independent scopes concurrently, but an
operation lease and source/target scope checks serialize one operation's active execution. Duplicate delivery after a
worker crash is expected and is safe only for a validly confirmed assertion and deterministic change ID. Retry is
owned by the worker until the bounded attempt limit; the operator owns terminal, ambiguous, authorization-invalid,
or provenance-invalid cases.

## SQLite-only/local

Knowledge events/current state, graph/suggestions/edges, retrieval index, and the operation journal share the local
`solomon.sqlite3` file. Individual journal changes and individual graph/knowledge operations use SQLite transactions;
the journal claim uses a persisted lease under `BEGIN IMMEDIATE`. This is atomic for statements in that transaction,
but not for the separate `sources.sqlite3`, workflow/authority SQLite files, retention registry, or JSONL audit file.

Source document versions and source-change events are authoritative in `sources.sqlite3`. A source revision can
temporarily exist with no graph re-verification operation after a crash. The inspector finds that deterministic
source-event/journal mismatch; safe reconciliation schedules reverification from immutable document/version lineage.
The audit JSONL is append-only and hash-chained, but its append occurs after a separate database phase; operation-ID
deduplication makes retrying that append safe. A completed operation has observed edge/currency/audit projections.

SQLite supports the documented offline single-writer envelope. Multiple independent processes sharing a reliable
local filesystem can use SQLite's database locking, but cluster-scale network-filesystem multi-writer use is not a
production claim.

## PostgreSQL server/production

Knowledge events/current state, graph/suggestions/edges, pgvector retrieval, and operations reside in the tenant's
PostgreSQL schema. PostgreSQL transactions make each repository change durable; operations are claimed with
row-level locking or a conditional update so concurrent workers cannot both own a lease. Existing repository calls
are not described as one transaction unless the code executes them through one explicit shared transaction.

Source documents, authority/workflow records, and audit remain local durable files/SQLite. Thus this is a mixed
SQLite/PostgreSQL profile, and no source-to-PostgreSQL or PostgreSQL-to-audit atomicity is claimed. The journal
records intent before graph/currency work; source events make a missing schedule detectable; projections are retried
until checkpointed or terminal. The production deployment must persist the PostgreSQL volume, source SQLite volume,
and audit-journal volume together in its backup/restore plan.

## Temporary states, inspection, and repair

Expected temporary states are queued/retrying operations, a valid confirmed assertion awaiting edge/currency/audit
projection, a source version awaiting a re-verification operation, or an existing edge awaiting operation
acknowledgement. They converge when an eligible worker retries before the configured maximum. A failed operation is
never silently discarded: it is queued, retrying, terminal failed, or operator required and appears in scoped status
and metrics.

Inspection is read-only, scope-bound, deterministic JSON. It reports missing expected edge, invalid/duplicate edge
provenance, stuck/unknown/missing operations, stale currency, scope mismatch, unreconstructible source reference,
and missing audit linkage. A repair plan is a sorted immutable description with a fingerprint over the scoped finding
versions. Dry run changes nothing; apply rechecks every finding version, refuses stale or cross-scope plans, writes a
repair audit event, and may only recreate an unambiguous projection of a still-valid confirmed assertion. It never
deletes evidence, compensates historical state automatically, or upgrades a pending/rejected/deferred/withdrawn
assertion.
