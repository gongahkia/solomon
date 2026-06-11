# ADR 0002: Bi-Temporal Model

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama must answer two different questions:

- What fact was valid for the user, repository, tool, or world at a given time?
- What did Shibahama know or believe at the time it answered a recall query?

Those questions diverge when facts are learned late, corrected after the fact, contradicted, or
reconstructed from stale sources. A single `created_at` timestamp cannot preserve that distinction.

## Decision

Every persisted memory item and graph edge carries two temporal dimensions:

- `valid_from` and nullable `valid_to`: the interval during which the fact or relationship is
  claimed to be true in the represented domain. `valid_to = null` means the valid interval is
  open-ended.
- `ingested_at`: the time Shibahama accepted the observation into its event log. Later schema work
  may add an explicit `superseded_at` for materialized ingestion-time intervals, but the event log
  is the source of record-time truth.

Default recall filters to facts valid at query time. Timeline queries can ask what was valid at an
arbitrary `as_of` time and, when needed, what Shibahama had ingested by an earlier observation time.

Invalidation closes `valid_to`; it does not delete the old item. Corrections append new events and
new item versions.

## Rationale

Bi-temporal modeling is the minimum model that supports Shibahama's currency promise. A coding
agent may learn today that `auth/session.ts` moved last month. The valid-time interval should
reflect last month; the ingestion-time history should show that Shibahama only learned the change
today.

The distinction also keeps reconstruction safe. A quarantined update can be represented as a new
low-credence observation without rewriting the earlier belief state.

## Consequences

- Public APIs must expose temporal intent clearly: "valid now" is the default, not the only query.
- Tests must cover late-arriving facts and invalidations that preserve the old row.
- Materialized views can optimize current lookups, but the event log must remain authoritative for
  historical reconstruction.
- Graph edges use the same temporal model as memory items to avoid special cases during traversal.
- Serialization formats must preserve open intervals without inventing sentinel timestamps.

## References

- Martin Fowler, "Bitemporal History": https://martinfowler.com/articles/bitemporal-history.html
- Martin Fowler, "Temporal Patterns": https://martinfowler.com/eaaDev/timeNarrative.html
