# ADR 0001: Storage Substrate

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama needs durable local storage for an in-process-first memory engine. The source of
truth is an append-only event log; current memory state is a materialized view. The storage
layer must support crash-safe writes, ordered reads, low operational overhead, and future
replacement by users with stricter deployment requirements.

The PRD explicitly frames Shibahama as SQLite-like infrastructure for agents, not a hosted
database. That makes a required external database a poor default.

## Decision

Use an embedded key-value store for the default materialized state and event-log indexes, with
`redb` as the first concrete backend. Define a Shibahama storage trait above the backend so that
RocksDB, SQLite, cloud object storage, or a hosted database can be implemented later without
changing the public memory API.

Vector search is separate from the KV substrate. Memory metadata and the event log remain in the
KV store; embedding vectors live behind a `VectorIndex` trait with backend-specific persistence.

## Rationale

`redb` is a pure Rust embedded KV store with ACID transactions, MVCC, copy-on-write B-tree
storage, and crash-safety as a default design goal. That fits the portfolio project's constraints:
simple installation, no C++ compilation path for the common case, and credible durability
semantics for a local memory engine.

`sled` is also pure Rust and embedded, but its long beta history and background flush semantics
make it less attractive as the default source-of-truth backend for a product whose core promise
is never silently losing memory history.

RocksDB remains a credible future backend for heavier deployments, but making it the first
default would impose native build complexity on Python and Node users before Shibahama has proven
its API and data model.

## Consequences

- The initial storage implementation can be distributed as a small Rust-native embedded library.
- The storage trait must be designed before backend-specific behavior leaks into the public API.
- Event-log writes and materialized-state updates must happen in one backend transaction when the
  backend supports it.
- Vector index consistency must be managed explicitly because vectors are not owned by the KV
  backend.
- Backend capability differences must surface through typed errors and feature flags, not hidden
  behavior changes.

## References

- `redb` docs: https://docs.rs/redb
- `redb` repository: https://github.com/cberner/redb
- `sled` repository: https://github.com/spacejam/sled
- `rocksdb` crate docs: https://docs.rs/crate/rocksdb/latest
