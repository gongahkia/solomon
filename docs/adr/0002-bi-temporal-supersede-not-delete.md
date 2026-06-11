<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0002: Bi-Temporal Store and Supersede-Not-Delete

## Status

Accepted.

## Context

Solomon must answer both "what is live now?" and "what did the firm know on a prior date?" Legal and
privilege review need valid-time and ingestion-time, not just a mutable latest row.

## Decision

Every durable knowledge record carries valid-time (`valid_from`, `valid_to`) and ingestion-time
(`ingested_at`). Changes are appended as events. Supersession closes `valid_to`, marks the predecessor
`Superseded`, links the successor, and never deletes the predecessor.

## Consequences

The current-state table is derived from an event log. Recovery can rebuild state from the log. Right-to-
erasure handling must be modeled explicitly rather than implemented as raw deletion.

