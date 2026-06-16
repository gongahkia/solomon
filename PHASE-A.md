# Phase A — Performance Proof: Buildable Spec

Referenced by `NEXT-TODO.md` items 22–27.

## Purpose

The Rust-first thesis is a performance claim with zero committed numbers. This
phase produces reproducible latency/throughput/footprint artifacts that (a)
substantiate "Rust-first, in-process, sub-millisecond local recall" and (b)
counter the funded competition's known weakness: graph-construction systems are
expensive and slow to make new memories retrievable. The headline property for
the chosen audience (coding agents, framework builders) is
**write-then-immediately-recallable** — a just-written fact is recallable on the
very next call, at local-disk latency, with no background processing window.

This phase uses **no LLM and no external system**. Everything is deterministic
and self-contained, which is why it goes first: lowest risk, highest confidence,
fully under our control.

## Deliverables (definition of done)

1. A `criterion` benchmark crate at `benchmarks/perf/` that builds and runs via a
   single documented command.
2. Committed raw output + generated Markdown tables under
   `benchmarks/results/perf/`, one file per scale tier, each carrying a full
   environment manifest.
3. A CI smoke job that runs the 1k tier and fails on gross regression.
4. A short `benchmarks/results/perf/README.md` summarizing the headline numbers
   and linking the raw artifacts.

## Layout

```
benchmarks/perf/
  Cargo.toml                 # criterion dev-dep; depends on shibahama core
  benches/
    write_latency.rs
    recall_latency.rs
    ingest_throughput.rs
    post_write_availability.rs
    tier_breakdown.rs
    hnsw_quality.rs
  src/
    harness.rs               # shared: store setup, synthetic corpus, manifest
  README.md
benchmarks/results/perf/
  README.md                  # headline summary table + links
  manifest-template.json
  scale-1k.{json,md}
  scale-10k.{json,md}
  scale-100k.{json,md}
  scale-1m.{json,md}
```

## Synthetic corpus (shared harness)

All benches draw from one deterministic generator in `src/harness.rs` so results
are comparable across benches.

- Embeddings: fixed dimension `D = 768` (state it in the manifest; if the core's
  default differs, use the core default and record it). Generate with a seeded
  RNG (`StdRng::seed_from_u64(seed)`), unit-normalized vectors.
- Content: short synthetic strings `item_{i}` — content size is not the variable
  under test here; keep it constant so latency reflects index/storage, not
  serialization of large blobs. Record the fixed content byte size in the
  manifest.
- Provenance/credence/tier: spread across the enum variants in a fixed,
  documented distribution (e.g. 70% Unverified, 20% ModelInferred, 10%
  VerifiedSource) so tier-breakdown benches have material in each tier.
- Seed is a harness constant, recorded in every manifest. Same seed → same
  corpus → comparable runs.

## What each bench measures

### `write_latency.rs` (item 22)
Single-item `write()` latency against a store already populated to the tier size.
Report p50/p95/p99. Measure write into a store at each scale tier (write cost can
grow with index size — that's a result worth showing).

### `recall_latency.rs` (item 22, 23)
`recall(query, k)` latency with `k = 10`. The query is a held-out vector NOT in
the corpus (generated from a disjoint seed offset) so it exercises real nearest-
neighbour search, not an exact hit. Report p50/p95/p99 at each scale tier. This
is the headline number.

### `ingest_throughput.rs` (item 22)
Items/second for a bulk ingest of N items into an empty store, for N at each
tier. Report total wall time and derived items/sec. Run single-threaded;
note in the manifest that this is single-threaded ingest.

### `post_write_availability.rs` (item 22 — the headline property)
The differentiator test. Sequence: populate to tier size → `write()` one new
distinctive item whose embedding is known → immediately `recall()` with that
exact embedding as the query → assert the new item appears in the top-k on the
*first* recall call. Report: (a) boolean availability (must be `true`), and (b)
the latency of that first post-write recall. A `false` here is a thesis failure
and must block the phase. This is the property no graph-construction competitor
can match without a processing delay.

### `tier_breakdown.rs` (item 25)
Recall latency split by where the matched content lives: hot (in-memory current
state) vs warm vs cold (rehydrated from `cold_content`). Construct the store so
the query's true neighbours sit in a known tier, then measure. Goal: demonstrate
hot < warm < cold, i.e. the tier model buys real latency, it isn't decoration. If
hot is NOT faster than cold, that's a finding — report it honestly, don't hide
it.

### `hnsw_quality.rs` (item 24)
Recall@k of the HNSW index vs exact brute-force ground truth. For a sample of
held-out queries, compute the exact top-k by linear scan over all embeddings,
then measure what fraction the HNSW path returns. Report recall@10. This keeps
the speed numbers honest: a fast index returning wrong neighbours is not a win.
Run this at 10k and 100k (brute force at 1M is expensive — note its omission).

## Metrics & reporting format

Every result file is JSON + a generated Markdown table. JSON shape:

```json
{
  "manifest": {
    "commit": "<git rev-parse HEAD>",
    "rustc": "<rustc --version>",
    "os": "<uname -a or equivalent>",
    "cpu": "<model>",
    "ram_gb": 0,
    "embedding_dim": 768,
    "content_bytes": 0,
    "seed": 0,
    "scale": "10k",
    "command": "<exact command run>",
    "timestamp_utc": "..."
  },
  "results": {
    "write_latency_ns": { "p50": 0, "p95": 0, "p99": 0 },
    "recall_latency_ns": { "p50": 0, "p95": 0, "p99": 0 },
    "ingest_items_per_sec": 0,
    "post_write_available": true,
    "post_write_recall_latency_ns": 0,
    "tier_latency_ns": { "hot": 0, "warm": 0, "cold": 0 },
    "hnsw_recall_at_10": 0.0,
    "resident_memory_bytes": 0
  }
}
```

`resident_memory_bytes`: capture process RSS after the store is populated to tier
size, before queries. On Linux read `/proc/self/statm` or use a small helper; if
a reliable cross-platform read isn't available, record peak allocator stats
instead and say which method was used in the manifest.

The Markdown table is generated from the JSON — do not hand-write numbers.

## Acceptance criteria

- [ ] `benchmarks/perf/` builds clean (`cargo build -p shibahama-perf`).
- [ ] One documented command runs all benches and writes all result files. State
      it in `benchmarks/perf/README.md`.
- [ ] All four scale tiers (1k/10k/100k/1M) have committed JSON + MD. If 1M is
      infeasible on the available machine, commit up to 100k and record the 1M
      omission + reason in the results README — do NOT fabricate or extrapolate.
- [ ] `post_write_available` is `true` at every tier (hard gate — a `false`
      blocks the phase and becomes a Gate 0-style bug).
- [ ] `hnsw_recall_at_10` is reported at 10k and 100k. If it is below ~0.90,
      flag it as a tuning issue, don't bury it.
- [ ] CI smoke (1k) runs in CI and fails on a p99 recall latency regression
      beyond a documented threshold.
- [ ] Every result file carries a complete manifest. No number ships without its
      reproduction recipe.

## Notes / pitfalls

- Build in `--release`; debug-build latency numbers are meaningless. Document
  this in the command.
- Warm up before measuring (criterion does this) so you're not timing cold
  caches / first allocations.
- Pin the seed; re-running must reproduce the corpus.
- Don't compare against external systems here — that's Phase B/C. This phase is
  Shibahama-internal proof only.
- If write latency grows super-linearly with index size, that's a real and
  reportable HNSW-insertion characteristic — surface it, it informs the "when not
  to use" story.
