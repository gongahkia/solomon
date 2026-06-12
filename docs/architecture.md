<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

Solomon is a Python 3.10+ FastAPI service and CLI. It is organized around durable currency evidence:

- `currency`: data models, currency evaluation, feeds, reports, and supersession proposals.
- `store`: SQLite event store, backend factory, encrypted artifacts.
- `graph`: bi-temporal dependency edges, propagation, and suggestions.
- `credence`: source-tier policy, load-bearing guardrails, prompt-context separation.
- `boundary`: Kaypoh review, pseudonymize, reidentify, scrub, and fail-closed policy.
- `orchestrator`: retrieval and model routing.
- `audit`: hash-chained metadata-only journal and audit-pack export.
- `api` and `cli`: public verbs.

## Request Lifecycle

1. Ingest creates a `KnowledgeItem` with provenance and source-derived credence.
2. The vendored Kaypoh-derived review engine gates storage before the item is written.
3. Dependency edges are manually tagged or suggested from boundary-sanitized text.
4. Authority changes propagate staleness through graph dependents.
5. Recall searches the local index, filters Live items by default, expands dependencies, and applies credence.
6. Model context is pseudonymized by the vendored boundary before any remote endpoint.
7. The audit journal records metadata-only evidence.

## Store

SQLite is the local default. Server deployments can set `SOLOMON_DATABASE_URL` to a `postgres://` or
`postgresql://` DSN and install the optional `solomon[server]` dependency for the psycopg driver. Both
backends preserve the same event-log contract: knowledge is written through append-only events and projected
into current state, dependency edges are bi-temporal, and the retrieval index stores deterministic hashed
vectors. Supersession closes `valid_to`, links the successor, and leaves the predecessor queryable in review
or historical modes.

In server mode, tenant services keep the existing filesystem isolation for local SQLite deployments. When
Postgres is configured, each tenant is mapped to a sanitized Postgres schema so tenant data does not share
tables.

## Boundary

The boundary engine is vendored under `src/solomon/boundary/engine/` from Kaypoh commit
`7415069e57d69398e2c44ef6ababafb0c04a988b`. If that in-process boundary errors, ingestion and model egress
fail closed.
