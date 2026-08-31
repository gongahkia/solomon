<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0010: Durable Operations And Reconciliation Across Persistence Boundaries

## Status

Accepted for the Crash Consistency and Reconciliation Proof milestone.

## Context

Solomon deliberately supports an offline SQLite SKU and an optional PostgreSQL server backend. At the decision point,
knowledge, graph, and retrieval can use one PostgreSQL tenant schema, but source documents and versions remain in a
SQLite document database; workflow, authority registration, and the JSONL audit journal are separate stores. Even
the existing PostgreSQL repository classes hold separate connections and commit their own transactions. The current
topology therefore cannot honestly claim one atomic transaction for source → assertion → edge → currency → audit.

Source SQLite is deliberate rather than accidental: it keeps the local offline SKU portable, supports encrypted source
content and filesystem synchronization without a service dependency, and is mounted in the existing production
profile. Replacing all source and audit persistence would be a broad migration of immutable evidence and hash-chain
semantics. The repository does not yet contain the migration, backup/restore, or compatibility evidence needed to
make that safer than explicit reconciliation.

## Considered approaches

| Approach | Correctness and recovery | Compatibility and deployment | Decision |
| --- | --- | --- | --- |
| 1. Consolidate all authoritative production state in PostgreSQL; make SQLite development-only | Could make a fully colocated subset atomic, but only after source documents, audit, registries, migration/restore, and deployment contracts are rewritten and proven. Current separate PostgreSQL connections still need a shared transaction coordinator. | Breaks the offline local contract, increases migration risk for immutable evidence, and does not preserve actual mixed deployments. Operationally simpler only after that large rewrite. | Rejected now; reconsider only after a dedicated migration/backup proof. |
| 2. Preserve mixed stores with a durable operation journal and idempotent projections | Records intent before cross-boundary effects, resumes after crashes, and detects missing projections without inventing atomicity. Semantic idempotency is constrained by edge uniqueness, operation IDs, change IDs, and audit deduplication. | Retains local SQLite and current Compose/Helm topology. Adds bounded worker, inspection, repair, migrations, and operator workflow. Testable with real SQLite and PostgreSQL. | Chosen. |
| 3. Hybrid: PostgreSQL transaction for all colocated effects plus reconciliation for mixed/legacy | Could reduce partial states inside PostgreSQL, but requires refactoring current knowledge/graph/index repositories onto one connection and carefully separating every file-backed effect. | More operational and test complexity than option 2 for this milestone; risks an overbroad persistence rewrite while source/audit remain external. | Deferred; option 2 can evolve toward this without changing operation IDs. |

## Decision

Use a durable operation journal selected with the knowledge/graph backend. SQLite-only deployments keep operation
records in the same local knowledge/graph SQLite database; PostgreSQL deployments keep them in the same isolated
tenant schema as graph/knowledge. This is a journal plus idempotent projection design, not an outbox claim for every
existing store and not a saga with automatic destructive compensation.

An operation is created before an authorized multi-stage projection. The worker claims it through database-backed
lease/CAS logic, validates the original scope/authorization constraints against current records, writes named
checkpoints, and retries only safe stages. PostgreSQL claims use row-level database coordination; SQLite claims use a
short write transaction and persisted lease/version check. A source-document change event is an SQLite-side durable
reconciliation marker. If it has no operation record after an interruption, inspection reports it and a guarded,
deterministic repair can create only the corresponding re-verification operation.

## Consequences

The system gains durable, inspectable, bounded convergence and explicit terminal failure states across the current
mixed topology. It does not gain distributed ACID: source document commits, PostgreSQL commits, and JSONL audit
appends remain separate boundaries. A completed operation means its documented expected projections were observed,
not that all writes occurred in one transaction. Ambiguous provenance, scope mismatch, missing unreconstructible
source versions, and stale plans require an operator; repair never promotes an unconfirmed or terminal-negative
assertion.

SQLite remains a supported offline/local profile. PostgreSQL with pgvector remains the recommended server/production
profile, with the source SQLite and audit volumes treated as required durable state and included in reconciliation and
backup/restore procedures. Existing API semantics remain synchronous where a caller asks to perform the operation;
the service schedules then drains the operation before returning when possible, while a worker/restart can finish a
crashed request.
