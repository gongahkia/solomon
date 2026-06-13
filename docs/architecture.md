# Architecture

Shibahama is an in-process-first memory engine for long-running LLM agents. The
current implementation is centered on a Rust core crate, with Python, Node,
CLI, optional HTTP server, benchmark, and Tideline debugger surfaces built
around the same core behavior.

The core design is intentionally event-sourced: durable history is append-only,
while the current memory state is a materialized view optimized for normal
recall.

## Component Map

| Component | Path | Responsibility |
| --- | --- | --- |
| Core API facade | `core/src/api.rs` | Stable high-level API: `write`, `recall`, `reinforce`, `why`, and `timeline`. |
| Data model | `core/src/model.rs` | Memory ids, provenance, bi-temporal bounds, credence, tiers, graph entities, graph relations, and access events. |
| Storage | `core/src/storage.rs` | Append-only event log, materialized state, snapshots, graph storage, compaction, auditing, and redb-backed persistence. |
| Vector retrieval | `core/src/vector.rs` | Pluggable vector-index trait plus in-process HNSW and an injected remote-transport adapter boundary. |
| Retrieval orchestration | `core/src/retrieval.rs` | Vector recall, valid-time filtering, ranking, graph expansion, read safety, and surfaced-access recording. |
| Significance | `core/src/significance.rs` | Transparent scoring from decay, access reinforcement, outcomes, contradiction penalties, and graph centrality input. |
| Reconstruction | `core/src/reconstruction.rs` | Staleness triggers, explicit reconstruction gate, quarantine, corroboration, and re-validation planning. |
| Read safety | `core/src/read_safety.rs` | Read-time neutralization of stored content that looks like role/directive text. |
| Consolidation | `core/src/consolidation.rs` | Bounded consolidation planning and resummarization-depth controls. |
| Anomaly detection | `core/src/anomaly.rs` | Suspicious provenance and contradiction-burst detection. |
| CLI and server | `shibahama-cli/src/main.rs` | Command-line commands and the optional HTTP server over the core API. |
| Python binding | `bindings/python/` | PyO3/maturin package exposing the core API to Python. |
| Node binding | `bindings/node/` | napi-rs package exposing the core API to ESM/CJS users. |
| Tideline debugger | `tideline/` | React/Vite UI for replaying event/state streams. |
| Benchmarks | `benchmarks/` | Harnesses and local result artifacts for Shibahama, feature ablations, and baselines. |

## Durable State Model

Every memory item has a stable UUIDv7 id, content, semantic kind, provenance,
bi-temporal bounds, tier, credence tier, significance score, credence floor, and
access-event history.

Two time axes are modeled separately:

- `valid_from` and `valid_to` describe when a fact is claimed to be true in the
  represented domain.
- `ingested_at` records when Shibahama accepted the observation.

Invalidation closes `valid_to`. It does not remove the memory row or erase the
event that introduced it. Corrections and reconstructions are represented as new
events and, when needed, new memory rows linked to superseded state.

The default embedded store is `RedbMemoryStore`. It maintains:

- an append-only `event_log` table for source-of-truth history;
- a `memory_items` materialized table for current item state;
- an `embeddings` table used to hydrate local vector indexes on startup;
- a `cold_content` table for compressed cold-tier payloads;
- graph entity and relation tables for retrieval expansion and contradiction
  handling.

Writes that touch the event log and materialized memory state use immediate
redb durability. The vector index is outside redb, so write paths that include
embeddings explicitly update both the durable embedding record and the active
`VectorIndex`.

## Write Lifecycle

The normal embedded write path is:

1. A caller creates a `MemoryWriteEvent` with mandatory provenance and valid
   time.
2. Ingestion assigns default credence from `SourceKind` unless the caller
   supplies an explicit credence.
3. The store assigns a UUIDv7 `MemoryId`, appends `MemoryWritten`, and updates
   materialized state.
4. If an embedding is supplied, the embedding metadata is persisted and the
   active vector index receives the vector.

Default ingest behavior is conservative:

- user memories start as `FirmAuthoritative`;
- file memories start as `VerifiedSource`;
- agent and tool memories start as `ModelInferred`;
- web memories start as `Unverified`;
- agent and web memories start cold by default.

Instruction memories are represented separately from fact memories through
`MemoryKind::Instruction`. Default recall excludes instructions unless the
caller opts in.

## Recall Lifecycle

The current recall hot path is id-bounded:

1. Search the active vector index for `top_k` candidate ids.
2. Fetch only those ids from storage with `get_many`.
3. Filter to facts believed at the request time: `ingested_at <= now` and
   `valid_from <= now < valid_to` when `valid_to` is present.
4. Exclude cold-tier memories and instruction memories unless requested.
5. Optionally expand through a caller-provided related-memory provider.
6. Build candidates with provenance, tier, currency, staleness flags, scoring
   components, and read-safety findings.
7. Rank by credence first, then weighted score, then id.
8. Diversify near-duplicate content.
9. Record a `Surfaced` access event for returned candidates.

Ranking combines vector similarity, materialized significance, optional recency,
and optional graph-expansion weight. Low-credence memories cannot outrank higher
credence memories on otherwise comparable retrieval because credence is the
first sort key.

`timeline` uses the same retrieval machinery but is read-only: it does not
record surfaced-access events. It answers what Shibahama had ingested and
believed at the requested instant.

## Significance And Tiers

Significance is intentionally explainable rather than learned. The default
function combines:

- time decay since last access or ingestion;
- diminishing-returns reinforcement from access count;
- outcome weights for surfaced, led-somewhere, cited, ignored, and contradicted
  events;
- contradiction penalties;
- optional graph centrality input.

Tier transitions are threshold based and lazy. Access can promote an item from
cold to warm or warm to hot. Decay can demote hot to warm or warm to cold, but
the proposed tier is clamped by the item's credence floor.

`why(memory_id)` exposes the current item, deterministic significance
breakdown, provenance, tier/credence state, currency state, and audit trail.

## Graph And Reconstruction

The graph substrate stores typed entities and typed directed relations using the
same bi-temporal model as memory items. Relations can carry a supporting
`memory_id`, a `supersedes` relation id, attributes, and valid-time bounds.

Graph features currently include:

- entity upsert and resolution through type plus stable key;
- relation insertion and traversal;
- contradiction detection for conflicting active relations on the same entity
  attribute pattern;
- supersession links when a new relation invalidates an old relation;
- scoped subgraph extraction;
- graph centrality as a significance input.

Reconstruction is not an automatic side effect of ordinary reads. Recall can
flag a significant, old, not-recently-validated memory as load-bearing and
possibly stale. Reconstruction work runs only when a caller enters explicit
re-validation mode.

The reconstruction path is designed around quarantine:

- proposed updates enter as low-credence, cold memories tagged for quarantine;
- promotion requires human confirmation, a high-credence source, or enough
  independent consistent observations;
- accepted replacements invalidate the superseded version instead of
  overwriting it;
- reconstruction events are emitted for replay and debugger consumers.

## Deployment Surfaces

The Rust core is the semantic source of truth. Other surfaces are adapters:

- The CLI supports store initialization, writing, recall, `why`, inspection,
  export, and optional server mode.
- The HTTP server is a thin wrapper over the same core API. It currently exposes
  `/healthz`, `/readyz`, `/inspect`, `/write`, `/recall`, `/why/{memory_id}`,
  and Tideline snapshot/recording/live endpoints.
- Server mode uses API-key authorization when configured, validates namespaces,
  prefixes namespace ownership into source refs, enforces a per-namespace memory
  quota, and emits metadata-only request logs.
- The Python and Node bindings call into the Rust core rather than reimplementing
  memory semantics.
- Benchmarks and examples exercise the same API surface used by the bindings and
  server.

## Performance Boundaries

Default recall must not scan the full materialized store or event log. The
regression test in `core/src/retrieval.rs` guards the production recall helper
against known whole-store APIs.

Whole-store reads are still valid in administrative paths such as inspection,
snapshot/export, readiness, Tideline snapshots, and tier-capacity enforcement.

The local latency budget is documented in `docs/performance.md` and measured by
`benchmarks/recall-latency.py --check-budget`.

## Current Limits

Some architecture pieces are represented as extension points rather than final
production implementations:

- `RedbMemoryStore` is the only concrete durable store backend.
- Remote vector support is an injected transport boundary, not a bundled network client.
- Multi-reader/single-writer or MVCC behavior is inherited from redb but has not
  yet been documented as a tested Shibahama concurrency contract.
- LoCoMo and LongMemEval benchmark runs still need external dataset exports.
- Publishing to crates.io, PyPI, and npm is intentionally outside the local
  architecture and requires registry credentials or trusted publishing setup.
