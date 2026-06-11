# Shibahama — Implementation TODO

A usage-aware, reconstructive memory engine for LLM agents.

Priority scale: **P0** = must exist for the thing to work at all · **P1** = core thesis / required for a credible launch · **P2** = strong differentiator · **P3** = polish / stretch / nice-to-have.
Phases run roughly in order but P-tags cut across them — do all P0s in a phase before P2s in the same phase.

---

## Phase 0 — Foundations & repo scaffolding

### Repo & tooling
- [x] (P0) Initialise monorepo: `core/` (Rust), `bindings/python/`, `bindings/node/`, `tideline/` (TS/React), `benchmarks/`, `examples/`, `docs/`
- [x] (P0) Set up Cargo workspace with the core crate and a `shibahama-cli` crate
- [x] (P0) Configure `rustfmt`, `clippy`, and deny-warnings in CI
- [x] (P0) Set up GitHub Actions: build + test matrix (linux/mac), lint, and binding smoke tests
- [x] (P0) Choose and pin a licence (MIT or Apache-2.0); add `LICENSE` and SPDX headers
- [x] (P0) Write minimal `README.md` stub (replaced properly in M4) and `CONTRIBUTING.md`
- [x] (P1) Add `CODEOWNERS`, issue templates, and a PR template
- [x] (P1) Set up semantic versioning + `CHANGELOG.md` (keep-a-changelog format)
- [x] (P2) Pre-commit hooks (fmt, clippy, secret scanning)
- [x] (P2) Reproducible dev environment (devcontainer or Nix flake)

### Core architectural decisions (write these down in `docs/adr/`)
- [x] (P0) ADR: storage substrate choice (embedded KV + pluggable vector index)
- [x] (P0) ADR: bi-temporal model (valid-time vs ingestion-time semantics)
- [x] (P0) ADR: tier model (hot/warm/cold; never-delete invariant)
- [x] (P0) ADR: in-process-first, optional-server deployment shape
- [x] (P1) ADR: significance function v0 (transparent, hand-tuned, not learned)
- [x] (P1) ADR: credence taxonomy and the credence-floor invariant
- [x] (P1) ADR: error model (recoverable vs fatal; how recall degrades gracefully)

---

## Phase 1 — Core data model & storage substrate (Rust)

### Memory item representation
- [x] (P0) Define `MemoryItem` struct: id, content, embedding ref, provenance, timestamps, tier, credence, significance
- [x] (P0) Implement stable ID generation (UUID v7 for time-orderability)
- [x] (P0) Define `Provenance` type: source kind (user / agent / file / web / tool), source ref, ingested-by
- [x] (P0) Define bi-temporal fields: `valid_from`, `valid_to` (nullable = open interval), `ingested_at`
- [x] (P0) Define `CredenceTier` enum: FirmAuthoritative / VerifiedSource / ModelInferred / Unverified (generic names for OSS)
- [x] (P0) Define `Tier` enum: Hot / Warm / Cold
- [x] (P0) Define `AccessEvent`: timestamp, query-context hash, outcome signal (led-somewhere / cited / ignored / contradicted)
- [x] (P1) Define `credence_floor` per item (clamp below which significance cannot push tier)
- [x] (P1) Add schema version field to every persisted item for forward migration

### Storage engine
- [x] (P0) Implement append-only event log (writes never destroy; the source of truth)
- [x] (P0) Implement primary KV store for current materialised item state (e.g. redb / sled / rocksdb — pick in ADR)
- [x] (P0) Implement `write(item)` → persists event + updates materialised state
- [x] (P0) Implement `get(id)` and `get_many(ids)`
- [x] (P0) Implement soft-invalidate: close `valid_to`, never delete the row
- [x] (P1) Implement compaction for cold-tier items (compress content, keep metadata + pointer)
- [x] (P1) Implement crash-safe writes (fsync policy / WAL) and a recovery path on startup
- [x] (P1) Snapshot + restore of full memory state to a single file (portability, SQLite-like ergonomics)
- [x] (P2) Pluggable storage backend trait so users can swap the KV engine
- [x] (P2) Encryption-at-rest hook (needed later for the legal variant; stub the trait now)

### Vector index integration
- [x] (P0) Define `VectorIndex` trait (add, search, delete-by-id, dimensions)
- [x] (P0) Implement one concrete backend (lancedb or in-process HNSW) behind the trait
- [x] (P0) Wire embedding storage so item ↔ vector stay consistent on invalidate
- [x] (P1) Implement second backend (qdrant or pgvector) to prove the trait is real
- [ ] (P1) Handle embedding model/version metadata so re-embeds are detectable
- [ ] (P2) Batch upsert path for bulk ingestion

---

## Phase 2 — The significance engine (the novel core, P1 thesis)

### Usage signal capture
- [ ] (P0) Implement `reinforce(memory_id, outcome)` API that appends an `AccessEvent`
- [ ] (P0) Capture access on every `recall()` automatically (which items were surfaced)
- [ ] (P1) Distinguish "surfaced" from "actually used" (caller signals which retrieved items mattered)
- [ ] (P1) Capture outcome signal: did the action after recall succeed / was the memory cited in output
- [ ] (P1) Capture contradiction events (a new fact conflicts with this one)
- [ ] (P2) Lightweight, privacy-safe query-context fingerprint (hash, not raw text) per access

### Significance computation
- [ ] (P0) Implement time-decay function over time-since-last-use (configurable half-life)
- [ ] (P0) Implement reinforcement term: each access boosts significance (with diminishing returns)
- [ ] (P1) Implement outcome-weighting: "led somewhere" boosts more than passive surfacing
- [ ] (P1) Implement contradiction penalty
- [ ] (P1) Implement recompute-on-access (lazy) so there is NO global maintenance scan
- [ ] (P1) Implement the credence-floor clamp (significance may fall, tier cannot drop below floor)
- [ ] (P2) Make the significance function pluggable/parameterised via config
- [ ] (P2) Expose a deterministic "explain significance" breakdown (powers `why()` + the debugger)
- [ ] (P3) Experiment harness to compare significance-function variants offline

### Tier transitions
- [ ] (P0) Implement threshold-based promotion (warm→hot, cold→warm) on access
- [ ] (P0) Implement threshold-based demotion (hot→warm→cold) as significance decays, lazily
- [ ] (P1) Enforce the never-delete invariant in code + a test that asserts no path deletes
- [ ] (P1) Emit tier-transition events to the event log (so the Tideline can replay them)
- [ ] (P2) Hysteresis / cooldown so items don't thrash between tiers
- [ ] (P2) Configurable tier-capacity limits (hot tier has a budget) with significance-based eviction-to-warm

---

## Phase 3 — Retrieval orchestrator (P1)

- [ ] (P0) Implement `recall(query, context)` returning ranked candidates
- [ ] (P0) Stage 1: vector similarity retrieval (top-k candidates)
- [ ] (P0) Stage 2: temporal filter — default to "valid now"; exclude invalidated facts from default results
- [ ] (P1) Stage 3: significance weighting in the ranking score
- [ ] (P1) Stage 4: graph-relationship expansion (pull in connected facts)
- [ ] (P1) Attach provenance + tier + currency-flag to every returned candidate (never bare text)
- [ ] (P1) Flag candidates that are "load-bearing but possibly stale" (significant + old + not recently validated)
- [ ] (P1) Implement `timeline(query, as_of)` — bi-temporal "what did I believe on date X"
- [ ] (P2) Tunable ranking weights (similarity ⊕ significance ⊕ recency ⊕ graph) via config
- [ ] (P2) Cold-tier retrieval requires explicit opt-in / costs a flag (so callers know they paid for it)
- [ ] (P2) Result diversification so near-duplicate memories don't dominate
- [ ] (P3) Query-time budget controls (max tokens of context to assemble)

---

## Phase 4 — Bi-temporal knowledge graph substrate (P1)

- [ ] (P0) Define entity + relationship types (generic: Entity, Relation, with typed edges)
- [ ] (P0) Implement graph storage co-located with the memory store
- [ ] (P0) Implement edge bi-temporality (relationships also have valid-time)
- [ ] (P1) Implement contradiction detection: new fact vs existing fact on same (entity, attribute)
- [ ] (P1) On contradiction → invalidate old (close valid_to), insert new, link them (supersedes edge)
- [ ] (P1) Implement graph traversal API for retrieval expansion (n-hop, typed)
- [ ] (P1) Implement graph centrality as a significance input (well-connected facts matter more)
- [ ] (P2) Entity resolution / dedup (same entity referred to differently)
- [ ] (P2) Subgraph extraction for a given matter/namespace/scope
- [ ] (P3) Graph snapshot at an arbitrary `as_of` time (full historical graph reconstruction)

---

## Phase 5 — Reconstruction & reconsolidation engine (P1, the Shibahama moment)

- [ ] (P0) Define the reconstruction trigger: recall of a flagged stale-but-significant memory
- [ ] (P0) Implement the gate — reconstruction NEVER fires automatically as a side effect of a plain read
- [ ] (P1) Implement re-validation hooks: re-read source (file/tool/graph) or surface to caller for confirmation
- [ ] (P1) Implement quarantine: proposed updates enter at LOWER credence, tagged, not promoted
- [ ] (P1) Implement corroboration rule: promotion needs a 2nd consistent observation / human confirm / high-credence source
- [ ] (P1) Implement invalidate-not-overwrite on the superseded version (preserve history)
- [ ] (P1) Emit reconstruction events to the log (so the Tideline can show the moment)
- [ ] (P2) Configurable re-validation strategies per provenance type
- [ ] (P2) Rate-limit / cost-cap reconstructions so a query storm can't trigger mass re-validation
- [ ] (P3) Async/background reconstruction option (validate-on-idle for known-stale significant facts)

---

## Phase 6 — Ingestion gate & poisoning resistance (P1, OWASP ASI06)

- [ ] (P0) Implement `write(event)` ingestion path with mandatory provenance
- [ ] (P0) Assign credence on ingest based on source kind (agent/web/tool default to lower)
- [ ] (P1) Quarantine model-generated and web-sourced content at low credence by default
- [ ] (P1) Enforce: low-credence items can never outrank authoritative ones in retrieval
- [ ] (P1) Bound auto-consolidation/summarisation to limit semantic drift (cap re-summarisation depth)
- [ ] (P1) Treat the memory store as an untrusted input surface — sanitise/validate on read of stored instructions
- [ ] (P2) Separate "facts" from "instructions" so retrieved memory can't inject directives
- [ ] (P2) Anomaly flags: sudden burst of contradictory writes, suspicious provenance
- [ ] (P2) Per-item audit trail of all credence/tier changes with cause
- [ ] (P3) Optional signed provenance (write attribution that can't be forged)

---

## Phase 7 — Public API & developer experience (P1, DX is priority #1)

### API surface
- [ ] (P0) Finalise the small API: `write`, `recall`, `reinforce`, `why`, `timeline`
- [ ] (P0) Make `why(memory_id)` first-class: full significance/tier/provenance/currency trace
- [ ] (P1) Stable error types with actionable messages
- [ ] (P1) Config object with sane defaults (decay half-life, thresholds, tier budgets)
- [ ] (P1) Streaming/iterator recall for large result sets
- [ ] (P2) Async API surface (tokio) alongside sync

### Python bindings (`pip install shibahama`)
- [ ] (P0) Set up PyO3 + maturin build
- [ ] (P0) Expose the full API with Pythonic types and type stubs (.pyi)
- [ ] (P0) Publish a working `pip install` from TestPyPI, then PyPI
- [ ] (P1) Async support that plays well with asyncio
- [ ] (P1) Integration shim for a popular agent framework (LangChain/LlamaIndex memory interface)
- [ ] (P2) Pandas/Arrow export of memory state for analysis

### TypeScript / Node bindings (`npm install shibahama`)
- [ ] (P0) Set up napi-rs build
- [ ] (P0) Expose the full API with TS types
- [ ] (P0) Publish a working `npm install`
- [ ] (P1) ESM + CJS dual package
- [ ] (P2) Integration shim for a JS agent framework

### CLI
- [ ] (P1) `shibahama` CLI: init a store, write, recall, why, inspect, export
- [ ] (P1) `shibahama serve` — start the optional server mode
- [ ] (P2) Pretty terminal output for `why` (a text version of the Tideline trace)

---

## Phase 8 — Optional server mode (P2)

- [ ] (P1) Implement a thin HTTP/gRPC server wrapping the same core API
- [ ] (P1) Namespace/scope isolation (multi-agent, multi-project)
- [ ] (P1) AuthN/AuthZ stub (API keys; pluggable for the legal variant)
- [ ] (P2) Per-namespace config + quotas
- [ ] (P2) Metadata-only request logging (who/when/cost, never content — matters for legal reuse)
- [ ] (P2) Health/readiness endpoints + graceful shutdown
- [ ] (P3) Horizontal-scale story (sharding by namespace)

---

## Phase 9 — The Tideline (visual debugger, P1 centrepiece)

### Plumbing
- [ ] (P0) Define a read-only event/state stream API the UI consumes (replay + live)
- [ ] (P0) Scaffold the TS/React app (Vite), connect to core via server mode or a local bridge
- [ ] (P1) Session recording format so a run can be saved and replayed in the UI
- [ ] (P1) Time-scrubber control (play/pause/seek over a session timeline)

### Views
- [ ] (P1) Tier map: memories as nodes, positioned by significance, coloured by tier
- [ ] (P1) Live drift animation: nodes move hot→warm→cold and snap back on access
- [ ] (P1) "Why did I get this?" panel: click a recalled memory → full `why()` trace
- [ ] (P1) Significance breakdown viz: decay curve + reinforcement events over time for one item
- [ ] (P1) The Shibahama-moment view: old fact invalidating, quarantined new fact entering at lower credence
- [ ] (P2) Poisoning view: quarantined/low-credence items visually walled off; show they can't outrank
- [ ] (P2) Bi-temporal scrubber: "show me the memory state as of date X"
- [ ] (P2) Graph view: entities + relationships with valid-time edges
- [ ] (P3) Diff view between two points in a session
- [ ] (P3) Export a view as the README GIF / shareable clip

---

## Phase 10 — Proof: benchmarks (P1/P2)

### Harness
- [ ] (P0) Build a benchmark harness (Python) that drives Shibahama, Mem0, and Zep through identical tasks
- [ ] (P0) Implement adapters for Mem0 and Zep so comparisons are apples-to-apples
- [ ] (P1) Deterministic seeds + logged configs so results are reproducible
- [ ] (P1) Metrics: recall accuracy, retrieval token cost, latency, stale-answer rate

### Existing suites
- [ ] (P1) Wire up LoCoMo and run all systems
- [ ] (P1) Wire up LongMemEval and run all systems
- [ ] (P1) Build a long-horizon coding-agent memory task (the headline scenario)
- [ ] (P1) Produce a results table (accuracy vs token-cost frontier) for the README
- [ ] (P2) Ablations: significance on/off, reconstruction on/off, graph on/off — isolate what each contributes

### CurrencyBench (P2/P3, the defensible new artifact)
- [ ] (P2) Design `CurrencyBench`: long-horizon task that injects fact CHANGES mid-stream
- [ ] (P2) Metrics: stale-answer rate, time-to-correction after a fact changes
- [ ] (P2) Run all systems; show the gap Shibahama is built to win
- [ ] (P3) Write up CurrencyBench as its own `benchmarks/currencybench/README.md` for citability
- [ ] (P3) Release the CurrencyBench dataset/generator so others can reproduce

---

## Phase 11 — Headline demo: the long-lived coding agent (P1)

- [ ] (P0) Build a minimal coding agent that uses Shibahama as its memory
- [ ] (P1) Seed it with a realistic multi-session repo history (decisions, rejections, file moves)
- [ ] (P1) Scenario A: agent does NOT re-suggest a previously rejected approach (credence floor working)
- [ ] (P1) Scenario B: agent re-validates a moved/renamed file before citing it (reconstruction working)
- [ ] (P1) Record the run so it replays in the Tideline (the demo GIF source)
- [ ] (P2) Side-by-side: same agent on a warehouse baseline failing both scenarios
- [ ] (P2) Package as a runnable `examples/coding-agent/` anyone can `clone && run`

---

## Phase 12 — Testing & correctness (P0/P1, cross-cutting)

- [ ] (P0) Unit tests for the data model, bi-temporal invariants, tier transitions
- [ ] (P0) Property test: no operation ever deletes a memory (the core invariant)
- [ ] (P0) Property test: invalidated facts never appear in default (valid-now) recall
- [ ] (P1) Property test: low-credence items never outrank authoritative on identical similarity
- [ ] (P1) Significance determinism test: same access history → same significance breakdown
- [ ] (P1) Reconstruction gate test: a plain read never mutates memory
- [ ] (P1) Crash-recovery test: kill mid-write, reopen, state is consistent
- [ ] (P1) Binding parity tests: Python and Node return equivalent results to the Rust core
- [ ] (P2) Fuzz the ingestion path (malformed/adversarial writes)
- [ ] (P2) Soak test: long-running agent over 10k+ sessions, assert no unbounded growth in hot tier
- [ ] (P2) Poisoning red-team test: attempt to promote a planted false fact, assert quarantine holds

---

## Phase 13 — Performance & hardening (P2)

- [ ] (P1) Benchmark recall latency (p50/p95) and set a budget
- [ ] (P1) Ensure no global scan exists anywhere on the hot path (lazy everything)
- [ ] (P2) Profile and optimise the significance recompute path
- [ ] (P2) Memory-footprint budget for embedded mode (must stay modest to justify "embeddable")
- [ ] (P2) Concurrency: safe multi-reader / single-writer (or MVCC) story, tested
- [ ] (P3) SIMD / batched vector ops where the index backend allows
- [ ] (P3) Optional mmap for cold-tier compressed store

---

## Phase 14 — Docs inside the repo (P1, minimal but essential)

- [ ] (P0) Deep `README.md`: thesis, the closed-loop diagram, quickstart, benchmark table, debugger GIF (README IS the paper)
- [ ] (P1) `docs/architecture.md`: components, data model, request lifecycle
- [ ] (P1) `docs/concepts.md`: significance, tiers, credence, reconstruction explained plainly
- [ ] (P1) API reference generated from doc-comments (rustdoc + typedoc + Python docstrings)
- [ ] (P1) `examples/` with runnable snippets per binding
- [ ] (P2) `docs/benchmarks.md`: methodology + how to reproduce
- [ ] (P2) `docs/security.md`: the ASI06/poisoning posture and what is/ isn't guaranteed
- [ ] (P2) ADR index kept current
- [ ] (P3) A short `docs/why-shibahama.md` telling the rakugo story + the design philosophy

---

## Phase 15 — Launch (P1/P2)

- [ ] (P0) Tag a real `v0.1.0`, publish crate + pip + npm
- [ ] (P1) Record the README demo GIF from the Tideline
- [ ] (P1) Write the Show HN post (lead with the embeddable-core + the "remembers why you said no" hook)
- [ ] (P1) Prepare a FAQ for the predictable HN objections (null hypothesis, "isn't this just a cache", security)
- [ ] (P2) A short launch blog post / writeup (optional, README may suffice)
- [ ] (P2) Reach out for early users / collect first issues
- [ ] (P3) Submit CurrencyBench writeup somewhere citable

---

## Phase 16 — Bridge to the legal-tech variant (P3 here; full scope in its own PRD)

- [ ] (P2) Confirm the encryption-at-rest trait and metadata-only logging hooks are in place
- [ ] (P3) Confirm forgetting can be globally disabled in favour of flag-for-reverification (config switch)
- [ ] (P3) Confirm credence taxonomy is swappable (generic OSS names → firm-authoritative/etc.)
- [ ] (P3) Stub the sanitising-gateway integration point (where tokenisation will sit) without building it here
