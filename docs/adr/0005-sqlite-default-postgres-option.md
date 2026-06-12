<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0005: SQLite Local Store with a Postgres Server Option

## Status

Accepted.

## Context

Solomon has two deployment shapes. `solomon-local` must run offline with no external service dependency.
`solomon-server` needs a path to higher concurrency and operational controls. Both shapes must preserve the
same append-only, supersede-not-delete semantics.

## Decision

SQLite is the default local store. It is embedded, durable, portable, and sufficient for a single-user
offline SKU. The storage interface is event-log shaped; the Postgres backend preserves the same events and
current-state projection without changing product semantics. The server storage bundle includes Postgres
implementations for the knowledge store, dependency graph, and deterministic retrieval index. The optional
driver dependency lives behind `solomon[server]`.

## Consequences

The local implementation uses SQLite WAL mode, transactional writes, and JSON event payloads. Server
deployments can select Postgres through `SOLOMON_DATABASE_URL` without weakening the local SKU or changing
the API contract. Server tenant admission is tracked in the tenant registry, including lifecycle state and
optional tenant-specific API-key hashes. Tenant storage remains isolated at the storage layer: SQLite uses
per-tenant files and Postgres uses per-tenant schemas.
