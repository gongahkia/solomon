<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production Deployment, Backup, Restore, And Upgrade Rehearsal Contract

## Locked scope

This contract starts at clean commit `2d74983b0724ab9f9b4d19a4c8b2bbf0288723ab`, after the crash-consistency and
reconciliation proof. It adds operational proof only: deployment preflight, deterministic bootstrap, migration
compatibility, coordinated full backup, guarded restore, upgrade rehearsal, and documentation. It does not alter
parsing, extraction, review, assertion, graph, currency, or MCP semantics.

The claim under test is deliberately bounded:

> Solomon provides a documented production profile with preflight validation, deterministic migrations, coordinated
> backup and restore, guarded upgrades, rollback-aware recovery, and post-operation verification across its supported
> persistence components.

This is not a claim of distributed ACID, zero downtime, point-in-time atomicity across PostgreSQL/SQLite/JSONL,
geographic disaster recovery, external RPO/RTO, or universal Kubernetes support.

## Canonical production rehearsal

The canonical, exercised profile is `docker-compose.production.yml` on one disposable host:

| Component | Rehearsal role | Durable location | Scaling rule |
| --- | --- | --- | --- |
| PostgreSQL 16 with pgvector | knowledge events/items, graph, suggestions, retrieval, operation journal | `postgres-data` volume | one database instance for this rehearsal |
| API | authenticated server API | no independent state | one replica |
| Console | authenticated operator console | no independent state | one replica |
| Worker | source sync and durable-operation recovery | shared local data/journal plus PostgreSQL leases | one replica; source sync has no distributed lease |
| local state | source documents/candidates, authority/workflow SQLite, registries | `solomon-data` volume | shared POSIX volume, not independently horizontally scalable |
| audit | append-only hash-chained JSONL | `solomon-journal` volume | shared POSIX volume; file locking is required |

The Compose profile is deliberately mixed-store. PostgreSQL migration transactions and each SQLite backup are atomic
only in their own stores. A bounded maintenance/checkpoint interval stops new local operation claims, drains or
records in-flight work, verifies leases, checkpoints SQLite, captures PostgreSQL and local state, then verifies a
complete manifest. The result is a recoverable coordinated checkpoint, not one distributed transaction.

The rehearsal uses an explicitly named disposable Compose project, isolated temporary directories, a loopback-only
port mapping, generated test secrets outside the repository, and a disposable pgvector container. It must never use
existing named volumes, real credentials, or an operator's configured data directories.

## Required implementation contract

### Operator commands

The CLI must expose non-interactive JSON interfaces for:

- deployment preflight and post-deployment verification;
- idempotent bootstrap/initialization;
- backup create, inspect, and verify;
- restore preflight/plan and explicit apply;
- upgrade preflight and status.

MCP remains read-only. Restore, initialization, backup maintenance state, and migration are never MCP mutations.
Commands must redact credentials, DSNs, evidence, and private keys.

### Compatibility and migration

Every persisted component needs recorded format/schema compatibility: PostgreSQL, local SQLite files, audit JSONL,
operation journal, and the backup manifest. A migration records start/completion/failure and uses a backend lock:
PostgreSQL advisory lock for the selected tenant schema and SQLite/file exclusion for local state. Concurrent migration
attempts fail safely. No command silently downgrades a schema or accepts a version jump whose intermediate migration
path is unknown.

Application rollback is allowed only when the target application declares the existing schema readable and does not
attempt writes beyond its maximum writable version. An incompatible rollback fails before startup. Database downgrade
is not automatic; a verified restore of the pre-upgrade backup or a forward repair is the recovery path.

### Coordinated full backup

The initial format is a full, versioned backup. It contains the PostgreSQL logical dump, safely copied SQLite
databases, bounded audit JSONL, and a manifest with component versions, tool/version identity, file sizes, SHA-256
hashes, operation checkpoint, quiescence result, exclusions, and completion state. It excludes runtime credentials,
environment files, content-encryption keys, and private deployment configuration. Hashes do not provide encryption;
the operator must keep the destination private and mode-restricted unless a separately supported encryption mechanism
is used.

Creation stages all artifacts below a validated destination. The manifest becomes complete only after every component
and hash verifies. A timeout, injection, or subprocess termination leaves an incomplete, non-restorable staging
record and clears maintenance mode. SQLite is copied only through SQLite's backup API. PostgreSQL is captured with a
real logical backup tool in the Compose rehearsal. No live database file copy is accepted.

### Guarded restore

Restore first verifies a manifest and produces a deterministic plan/fingerprint. Apply requires that exact plan,
explicit authorization, an empty validated target, and unchanged manifest/destination state. Extraction rejects path
traversal, links, duplicate or unexpected entries, unsafe counts/sizes, tampering, truncation, and unsupported
formats. It stages all component data, validates SQLite integrity and PostgreSQL restore, verifies the audit chain,
runs scoped consistency inspection and safe reconciliation, compares a semantic inventory, then activates each
staged component. Existing target data is never silently deleted.

### Rehearsal fixture and failures

The N-to-N+1 fixture is a real committed starting-revision fixture when one is compatible with the bounded source
tree; otherwise it is a separately versioned, documented fixture whose schema identity predates the new backup
metadata. It contains source/version lineage; pending, confirmed, rejected, deferred, withdrawn, and stale/reverify
assertions; graph/currency effects; a recoverable journal record; and an audit pack.

The headless proof injects preflight, lock, PostgreSQL/SQLite migration, drain, PostgreSQL/SQLite backup, audit,
manifest, restore staging, integrity, reconciliation, and post-migration startup failures. It includes one bounded
subprocess termination. For each case it records mutation status, maintenance cleanup, backup completion state, safe
retry status, and operator-required state.

## Locked acceptance gates

The milestone may pass only when the real pgvector/SQLite Compose rehearsal proves a fresh deploy, preflight,
bootstrap, governed workflow, queued recovery, complete backup, upgrade, restore to an isolated empty target,
semantic inventory equality, audit-pack verification, and a valid post-restore write. It must also prove corrupt,
incomplete, unsafe, stale, and cross-target restore attempts fail closed; migration contention and incompatible
rollback are refused; parser baselines do not change; full coverage remains at least 90%; and the existing lint,
typing, security, dependency, package, Helm/Compose, CLI/MCP, binary, and release-quality gates pass.

## Non-goals and known environmental boundary

Kubernetes runtime proof is not currently planned because this environment has Helm but no `kubectl`, Kind, or k3d.
The chart will receive static validation only and remains experimental until a local-cluster rehearsal is recorded.
No incremental backup, remote object store, backup encryption redesign, default credentials, setup wizard, or pilot is
part of this milestone.

If the proof passes, the next recommendation is the bounded owner-operated pilot on a small non-sensitive internal
knowledge set—not another synthetic infrastructure milestone.
