# ADR 0009: Never-Delete Invariant Scope

- Status: Accepted
- Date: 2026-07-02

## Context

Shibahama's public claim is that memory history is never deleted. The implementation preserves
memory rows, event-log records, provenance, audit events, valid-time history, and compacted cold
content, but invalidation removes secondary vector-index entries and persisted embedding rows.

That distinction is intentional but must be explicit. A reviewer should not have to infer whether
"never delete" includes regenerable retrieval indexes, and the engine should not present derived
index pruning as source-data retention.

## Decision

Scope the never-delete invariant to source and event memory state:

- append-only event-log records;
- materialized memory rows for every written memory id;
- provenance and ingestion metadata;
- valid-time invalidation history;
- human signal audit events;
- reconstruction and consolidation lineage;
- compacted cold-content payloads referenced by memory rows.

Derived retrieval state is outside the invariant:

- in-memory vector-index entries;
- persisted embedding rows used to hydrate local vector indexes;
- future cache rows, ANN graph layers, or search acceleration files.

Derived state may be deleted, tombstoned, compacted, or regenerated as long as the source/event
memory state remains sufficient to audit what happened and rebuild the derived representation when
the caller supplies the needed embedding model or indexing backend.

## Rationale

Embeddings and vector indexes are retrieval accelerators, not memory history. Keeping an embedding
for an invalidated memory in the active index would make stale content easier to retrieve by
accident. Deleting the derived row on invalidation reduces that risk without erasing the durable
memory item, the invalidation event, or the audit trail.

The stronger invariant is that source/event state remains recoverable and explainable. If an
embedding model changes, dimensions change, or a vector backend is rebuilt, derived rows should be
discardable. The caller can re-embed retained memory rows from source state when appropriate.

## Consequences

- Code and docs must say "source/event memory state is never deleted" when precision matters.
- Tests for `verify_never_delete_invariant` cover memory rows, event-log history, provenance, and
  compacted cold content, not derived embeddings.
- Invalidation may remove active vector entries and persisted embedding rows.
- Future derived indexes must be rebuildable from retained memory rows or explicitly documented as
  lossy caches.
- If a future feature needs embedding auditability, it must store that as source/event metadata or
  tombstone embedding rows explicitly instead of broadening the invariant by accident.
