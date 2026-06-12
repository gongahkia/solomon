# Performance Notes

## Recall Latency Budget

Use `python benchmarks/recall-latency.py --check-budget` to measure embedded recall latency. The
default local budget is p50 <= 25 ms and p95 <= 75 ms for 1,000 memories, 200 measured queries,
16-dimensional deterministic embeddings, and top-k 5.

This budget covers the in-process Rust core through the Python binding. It does not include hosted
embedding calls, external memory adapters, or network transport.

## Embedded Memory-Footprint Budget

Use `python benchmarks/memory-footprint.py --check-budget` after building the
Python binding to measure resident memory growth for an embedded temporary
store. The default local budget is RSS delta <= 128 MiB for 1,000 memories,
16-dimensional deterministic embeddings, capacity 1,000, and top-k 5.

The script reports RSS baseline, RSS after seeding and one recall, RSS delta,
and temporary database size as JSON. The budget intentionally measures the
in-process binding plus Rust core together because that is the embeddable shape
most Python users exercise locally.

## Significance Recompute Profile

Use `python benchmarks/significance-recompute.py --check-budget` after building
the Python binding to profile the public `why()` path over one memory with a
long access history. The default local guardrail is p95 <= 20 ms for 1,000
access events and 200 measured explanations.

The core scorer summarizes access history in one pass when computing
last-used time, outcome contribution, and contradiction penalty. The benchmark
keeps this optimisation measurable through the same binding path users call for
debugging significance.

## Batched Vector Operations

The `VectorIndex` trait includes both `batch_upsert` and `search_batch`.
Backends can override either method when their native API can execute a true
batch. The in-process HNSW adapter validates all query dimensions up front and
then runs the backend search for each query. The Qdrant adapter forwards batch
search through the transport boundary, whose default implementation falls back
to repeated searches when a concrete transport has no native batch endpoint.

No portable SIMD implementation is claimed for the current HNSW dependency. The
portable contract is batched vector operation support; SIMD can be added behind
the same methods if a backend exposes it.

## Cold-Tier Mmap Decision

Cold-tier compaction currently stores compressed payloads in the embedded redb
`cold_content` table. `RedbMemoryStore::compact_cold_item` moves cold item text
out of the materialized memory row, writes an LZ4 size-prepended payload into
that table, and leaves a `CompactionRef` pointing at the table key.

The v0.1 decision is to keep that design and not add mmap. A real mmap path
needs a separate cold-content file/backend layout with stable offsets, lengths,
integrity metadata, and a migration path from existing redb `cold_content`
records.

The usual Rust mmap crate choice, `memmap2`, marks file-backed map constructors
as `unsafe` because the compiler cannot prove the underlying file will not be
modified or truncated while mapped. This repository currently sets
`unsafe_code = "forbid"` at the workspace level, so adding a direct memmap2 path
would require an explicit unsafe-code policy change and audit.

I also checked safe-public-API mmap wrappers. `mmap-rs` still requires unsafe for
file-backed `with_file`, while `tiverse-mmap` advertises a safe public API but
its published 1.0.0 documentation still shows examples as incomplete. The mmap
item is therefore closed as rejected/deferred for v0.1 in
[`ADR 0008`](adr/0008-cold-tier-mmap.md), not as an implemented feature.

## Hot-Path Scan Boundary

Shibahama's recall path is intended to be lazy and id-bounded. A normal recall should:

1. Search the vector index for `top_k` candidate ids.
2. Read only those ids from storage with `get_many`.
3. Optionally expand through a related-memory provider by explicit related ids.
4. Record surfaced access events for returned candidates.

The recall hot path must not scan the full materialized store or event log. The regression test in
`core/src/retrieval.rs` guards against calls to known whole-store APIs from production recall
orchestration.

Whole-store scans are still allowed in administrative paths where the caller asks for aggregate
state, including server readiness, server inspection, export, snapshot, and tier-capacity
enforcement. Those paths must stay outside default recall.

## Embedded Concurrency Boundary

The embedded `RedbMemoryStore` is intended to be shared as one database handle
across threads with many short read transactions and one writer transaction at a
time. `redb` supplies MVCC-style read transactions for committed state, while
write transactions serialize through the backend.

The regression test `redb_store_allows_concurrent_readers_with_a_single_writer`
asserts that the store is `Send + Sync`, keeps an existing memory readable from
several reader threads, and commits a single writer's appended memories without
corrupting the event log or materialized item table.

This does not make one `Shibahama` engine instance multi-writer at the API
level. The engine also owns a mutable vector index, so server and async wrappers
continue to serialize full-engine mutations around their existing lock. Systems
that need multi-writer fan-in should queue writes or shard by namespace rather
than sharing one mutable vector index without coordination.
