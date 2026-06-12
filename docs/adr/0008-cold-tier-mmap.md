# ADR 0008: Cold-Tier Mmap

- Status: Accepted
- Date: 2026-06-12

## Context

Cold-tier compaction currently stores LZ4 size-prepended payloads in the redb
`cold_content` table. The materialized memory row keeps metadata, provenance,
and a `CompactionRef`; only the large content string moves out of the hot row.

The open P3 question was whether to add an mmap-backed cold-content store. A
real mmap implementation would need a separate append-only content file, stable
offset and length metadata, integrity checks, migration from existing redb
records, and crash-recovery rules for the file plus redb index together.

The workspace also sets `unsafe_code = "forbid"`. The common `memmap2` path
requires unsafe file-backed map construction because Rust cannot guarantee that
another process will not mutate or truncate the mapped file. `mmap-rs` still
marks file-backed mapping setup unsafe. `tiverse-mmap` advertises a safe public
API, but the published 1.0.0 documentation still shows examples as not yet
complete, which is not a strong enough dependency signal for this storage path.

## Decision

Do not add mmap to the v0.1 cold-tier compressed store.

Keep the current redb-backed compressed cold-content table as the supported
backend for v0.1. Treat mmap as a future storage-backend redesign, not a hidden
optimization inside `RedbMemoryStore::compact_cold_item`.

Any future mmap-backed backend must:

- preserve the never-delete invariant;
- keep metadata and provenance queryable without mapping large content;
- use an explicit storage format with offset, length, codec, and checksum;
- include crash-recovery tests that cover redb/file disagreement;
- satisfy the workspace unsafe-code policy through an audited dependency or a
  separately approved unsafe-code policy change.

## Rationale

Adding mmap directly to the current redb table would not provide real mmap
benefits because redb owns the page layout and value access. Adding a separate
file backend just for this P3 item would expand the durability surface without a
measured latency or memory problem that justifies it.

The current compressed cold table already removes cold content from the
materialized row while preserving the API and snapshot model. That is the right
v0.1 tradeoff.

## Consequences

- Cold-tier content remains compressed in redb for v0.1.
- The mmap TODO is closed as rejected/deferred for this release, not marked as
  implemented.
- Future mmap work should start as a new storage-backend ADR and benchmark
  target, with safety and recovery tests written before claims are made.
