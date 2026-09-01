<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0011: Single-Host Mixed-Store Production Operations Profile

## Status

Accepted for the Production Deployment, Backup, Restore, and Upgrade Rehearsal milestone.

## Context

The earlier crash-consistency proof established that the server deployment is intentionally mixed: PostgreSQL holds
knowledge, graph, retrieval, and durable operations, while source documents/versions, authority and workflow state,
retention metadata, and the audit chain remain on a local SQLite/JSONL volume. PostgreSQL and each SQLite database
can make their own transactions durable. They do not participate in one cross-store transaction.

The repository contains two Compose files and a Helm chart. `docker-compose.server.yml` mounts the checkout and is a
development loop. `docker-compose.production.yml` uses immutable images, named volumes, secret files, a pinned
PostgreSQL 16 + pgvector image, one migration job, API, console, and one worker. Helm has static template validation,
but this environment has no local Kubernetes cluster evidence. Source SQLite and JSONL require a reliable shared
POSIX filesystem, so independently scaling API/worker processes is not a supported topology.

## Options considered

| Option | Correctness and recovery | Operations and compatibility | Decision |
| --- | --- | --- | --- |
| PostgreSQL-only production rewrite | Would remove some local-state boundaries only after source, workflow, retention, audit, migration, and restore conversion. JSONL/audit semantics would still need a new design. | High migration risk to immutable evidence; breaks the existing offline profile and is unsupported by current backup evidence. | Rejected for this milestone. |
| Treat development Compose or raw service process as production | Has no immutable image, controlled bootstrap, coordinated checkpoint, or supported volume contract. | Simple to start but not an honest production support statement. | Rejected. |
| Single-host production Compose, mixed PostgreSQL/SQLite/JSONL, coordinated maintenance checkpoint | Preserves each component's authoritative data, names the non-atomic boundary, and provides encrypted full backup, plan-before-apply restore, preflight, migration serialization, and a real disposable rehearsal. | Lowest migration risk; one worker and three durable stores are explicit operator requirements. | Chosen. |
| Helm/Kubernetes as the primary profile | Could be valuable once storage class, disruption, backup, and restore are rehearsed in a real cluster. | Only static chart evidence exists now; no cluster availability proof. | Experimental only. |

## Decision

The recommended profile is `docker-compose.production.yml` on one host. The minimum durable set is:

- PostgreSQL 16 + pgvector, for knowledge, graph, retrieval, and operation records;
- `solomon-data`, for source/version, workflow, authority, and retention state; and
- `solomon-journal`, for the hash-chained audit journal.

The profile starts a migration job, then an idempotent bootstrap job, before long-running services. PostgreSQL
migrations take a transaction-scoped advisory lock. Bootstrap takes a file lock and records one immutable deployment
marker. The application is stopped or maintenance-gated for the bounded backup interval; the worker then makes no
new claims and service mutation is refused.

The migration job initializes the base schema. API, console, worker, and their health probes open verified existing
schemas without DDL, so an ordinary readiness probe does not block behind a relation lock held by a live request. The
authenticated tenant-provisioning path is the narrow exception: it initializes a new isolated schema before publishing
the tenant registry entry. This deployment sequencing does not make application writes or mixed stores atomic.

A server backup is an encrypted full checkpoint: SQLite copies use SQLite's backup API; PostgreSQL uses `pg_dump`
custom format; audit JSONL is verified; and an encrypted archive plus sidecar manifest are atomically published only
after all components complete. Restore is deliberately separate: it validates the encrypted archive and audit chain,
creates a stable plan/fingerprint for an absent local target and an empty PostgreSQL database, then applies the
unchanged plan. The PostgreSQL restore itself uses `pg_restore --single-transaction`. There is no claim that the
PostgreSQL restore and local-volume activation are one transaction.

The only automatic rollback story is a restore of a verified pre-upgrade checkpoint. The upgrade preflight reports
this explicitly; an older binary is expected to reject an unknown newer schema migration rather than writing to it.

## Consequences

This gives a tested, portable single-host recovery procedure without claiming cross-store atomicity, zero downtime,
point-in-time recovery, off-host replication, or Kubernetes recovery. A crash after PostgreSQL restore but before
local activation can leave a restored database with no activated local root; the operator must preserve the evidence,
inspect it, and choose a fresh-target restore or a verified checkpoint restore. The tool never automatically deletes
the target database or historical source/audit evidence to compensate.

The two real-container rehearsals are intentionally isolated and vendor-neutral apart from the documented PostgreSQL
16/pgvector image. They create a checkpoint/restore into a distinct database host and run an old committed binary
followed by the current binary against one database. They are evidence for this profile only, not a managed-service,
multi-host, or Helm guarantee.
