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
2. Kaypoh review can gate storage when the boundary adapter is used.
3. Dependency edges are manually tagged or suggested from Kaypoh-sanitized text.
4. Authority changes propagate staleness through graph dependents.
5. Recall searches the local index, filters Live items by default, expands dependencies, and applies credence.
6. Model context is Kaypoh-pseudonymized before any remote endpoint.
7. The audit journal records metadata-only evidence.

## Store

SQLite is the local default. Knowledge is written through append-only events and projected into current
state. Supersession closes `valid_to`, links the successor, and leaves the predecessor queryable in review
or historical modes.

## Boundary

Kaypoh is an external sibling dependency, not vendored source. Solomon imports its client from `../kaypoh`
or calls a configured service URL. If Kaypoh is down, model egress fails closed.

