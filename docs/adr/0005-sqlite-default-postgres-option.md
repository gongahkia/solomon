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
offline SKU. The storage interface is event-log shaped so a later Postgres implementation can preserve the
same events and current-state projection without changing product semantics.

## Consequences

The first implementation uses SQLite WAL mode, transactional writes, and JSON event payloads. Server
deployments can add Postgres without weakening the local SKU or changing the API contract.

