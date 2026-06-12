# Architecture Decision Records

This directory records accepted architecture decisions for Shibahama. When a new
ADR is added, append it to this index with its status and date.

| ADR | Status | Date | Decision |
| --- | --- | --- | --- |
| [0001: Storage Substrate](0001-storage-substrate.md) | Accepted | 2026-06-11 | Use an embedded KV store as the default durable substrate, with redb first and vector search behind a separate trait. |
| [0002: Bi-Temporal Model](0002-bitemporal-model.md) | Accepted | 2026-06-11 | Store valid-time and ingestion-time separately for memory items and graph edges. |
| [0003: Tier Model](0003-tier-model.md) | Accepted | 2026-06-11 | Model accessibility as hot, warm, and cold tiers; decay demotes without deletion. |
| [0004: In-Process First, Optional Server](0004-deployment-shape.md) | Accepted | 2026-06-11 | Keep the Rust core as the semantic source of truth, with optional server mode as a thin wrapper. |
| [0005: Significance Function v0](0005-significance-function-v0.md) | Accepted | 2026-06-11 | Start with an explainable deterministic significance function rather than a learned scorer. |
| [0006: Credence Taxonomy and Floor](0006-credence-taxonomy.md) | Accepted | 2026-06-11 | Separate trust from usefulness with credence tiers and credence floors. |
| [0007: Error Model and Graceful Degradation](0007-error-model.md) | Accepted | 2026-06-11 | Use typed, actionable errors; fail writes closed and make degradation visible. |
| [0008: Cold-Tier Mmap](0008-cold-tier-mmap.md) | Accepted | 2026-06-12 | Keep v0.1 cold content in the compressed redb table; defer mmap to a future storage-backend redesign. |
