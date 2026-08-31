<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crash Consistency Architecture Narrative

Solomon deliberately chose a recovery proof over an invented distributed transaction. The server profile keeps
knowledge, graph, pgvector retrieval, and the operation journal in PostgreSQL, but immutable source documents remain
in SQLite and the audit journal is hash-chained JSONL. That topology supports offline evidence handling and existing
deployments, but means source-to-graph and graph-to-audit writes are separate durable boundaries.

The control point is a small operation journal, not a generic workflow engine. A reviewed suggestion or governed
confirmation, source revision, authority change, deterministic suggestion, or required audit phase receives an immutable operation ID,
scope, actor/authorization summary, idempotency key, and requested transition. Workers persist leases and phase
checkpoints. PostgreSQL workers claim with row locking; SQLite uses a short write transaction and durable lease.
Delivery is at least once; semantic effects are idempotent where Solomon proves an invariant, including one graph
edge per confirmed assertion and one change-ID currency impact.

A failure after an edge but before acknowledgement is therefore normal: restart rereads the provenanced edge,
checkpoints it, and does not create another edge. A failure before an operation is scheduled is different: source
changes, knowledge items, assertions, and authority events are reconstructible markers that the worker scans to
create the missing safe operation. Inspection reports every state it cannot safely complete. Repair is explicitly
planned, fingerprinted, dry-run by default, stale-plan checked, and limited to an existing valid confirmed assertion
or source-lineage re-verification. An orphan edge, invalid provenance, cross-scope record, corrupt audit reference,
or unreconstructible source is operator work, not an automatic compensation.

The tradeoff is intentional. A full PostgreSQL consolidation could shrink some partial states, but would be a risky
migration of immutable evidence, audit semantics, and the offline local profile; it still would not make JSONL atomic
without a larger redesign. The present architecture makes failures observable and convergent while saying precisely
what it does not guarantee: no distributed ACID transaction and no automatic legal or human-review decision.
