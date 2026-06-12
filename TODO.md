# Shibahama — Implementation TODO

A usage-aware, reconstructive memory engine for LLM agents.

Priority scale: **P0** = must exist for the thing to work at all · **P1** = core thesis / required for a credible launch · **P2** = strong differentiator · **P3** = polish / stretch / nice-to-have.
Phases run roughly in order but P-tags cut across them — do all P0s in a phase before P2s in the same phase.

---

## Stop point / next work

Updated on 2026-06-12 after completing the local implementation, performance, Tideline, API-reference, and launch-assets pass.

Current local state:
- The working tree is expected to be clean after the latest task commit.
- This branch is ahead of `origin/main` by the local task commits from this pass.
- Phase 5 now includes opt-in idle/background reconstruction planning for known-stale significant facts.
- Phase 9 now has the Tideline diff view and browser-native shareable WebM clip export.
- Phase 13 now has significance recompute profiling/optimisation, embedded memory-footprint budget, tested multi-reader/single-writer store concurrency, and batched vector search.
- Phase 14 now has architecture, concepts, benchmarks, security, ADR index, naming/philosophy docs, runnable Rust/Python/Node examples, and a generated API reference.
- Phase 15 now has draft Show HN, FAQ, launch writeup, and early-user outreach notes.
- Phase 16 legal-tech bridge confirmations are complete.

Still not done / next up:
- Publishing is blocked on registry credentials or trusted publishing setup:
  - TestPyPI/PyPI publish for `pip install`.
  - npm publish for `npm install`.
  - final `v0.1.0` tag + crate/pip/npm publish.
- Benchmarks:
  - Run LoCoMo through all systems once a dataset export and external service credentials/config are available.
  - Run LongMemEval through all systems once a dataset export and external service credentials/config are available.
  - Implement real ablations for significance/reconstruction/graph toggles; do not mark done with placeholder labels.
  - Run Mem0 and Zep adapters with real credentials/config to complete the "all systems" CurrencyBench gap claim.
- Performance:
  - Optional mmap for cold-tier compressed store still needs a separate cold-content file/backend design; current cold content lives in the redb `cold_content` table.
- Documentation:
  - Replace the stub README with the full thesis/quickstart/benchmark/debugger narrative.
- Launch assets:
  - Record the Tideline README demo GIF.
  - Actually reach out to early users and collect first issues.
  - Submit CurrencyBench writeup somewhere citable.

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
- [x] (P1) Handle embedding model/version metadata so re-embeds are detectable
- [x] (P2) Batch upsert path for bulk ingestion

---

## Phase 2 — The significance engine (the novel core, P1 thesis)

### Usage signal capture
- [x] (P0) Implement `reinforce(memory_id, outcome)` API that appends an `AccessEvent`
- [x] (P0) Capture access on every `recall()` automatically (which items were surfaced)
- [x] (P1) Distinguish "surfaced" from "actually used" (caller signals which retrieved items mattered)
- [x] (P1) Capture outcome signal: did the action after recall succeed / was the memory cited in output
- [x] (P1) Capture contradiction events (a new fact conflicts with this one)
- [x] (P2) Lightweight, privacy-safe query-context fingerprint (hash, not raw text) per access

### Significance computation
- [x] (P0) Implement time-decay function over time-since-last-use (configurable half-life)
- [x] (P0) Implement reinforcement term: each access boosts significance (with diminishing returns)
- [x] (P1) Implement outcome-weighting: "led somewhere" boosts more than passive surfacing
- [x] (P1) Implement contradiction penalty
- [x] (P1) Implement recompute-on-access (lazy) so there is NO global maintenance scan
- [x] (P1) Implement the credence-floor clamp (significance may fall, tier cannot drop below floor)
- [x] (P2) Make the significance function pluggable/parameterised via config
- [x] (P2) Expose a deterministic "explain significance" breakdown (powers `why()` + the debugger)
- [x] (P3) Experiment harness to compare significance-function variants offline

### Tier transitions
- [x] (P0) Implement threshold-based promotion (warm→hot, cold→warm) on access
- [x] (P0) Implement threshold-based demotion (hot→warm→cold) as significance decays, lazily
- [x] (P1) Enforce the never-delete invariant in code + a test that asserts no path deletes
- [x] (P1) Emit tier-transition events to the event log (so the Tideline can replay them)
- [x] (P2) Hysteresis / cooldown so items don't thrash between tiers
- [x] (P2) Configurable tier-capacity limits (hot tier has a budget) with significance-based eviction-to-warm

---

## Phase 3 — Retrieval orchestrator (P1)

- [x] (P0) Implement `recall(query, context)` returning ranked candidates
- [x] (P0) Stage 1: vector similarity retrieval (top-k candidates)
- [x] (P0) Stage 2: temporal filter — default to "valid now"; exclude invalidated facts from default results
- [x] (P1) Stage 3: significance weighting in the ranking score
- [x] (P1) Stage 4: graph-relationship expansion (pull in connected facts)
- [x] (P1) Attach provenance + tier + currency-flag to every returned candidate (never bare text)
- [x] (P1) Flag candidates that are "load-bearing but possibly stale" (significant + old + not recently validated)
- [x] (P1) Implement `timeline(query, as_of)` — bi-temporal "what did I believe on date X"
- [x] (P2) Tunable ranking weights (similarity ⊕ significance ⊕ recency ⊕ graph) via config
- [x] (P2) Cold-tier retrieval requires explicit opt-in / costs a flag (so callers know they paid for it)
- [x] (P2) Result diversification so near-duplicate memories don't dominate
- [x] (P3) Query-time budget controls (max tokens of context to assemble)

---

## Phase 4 — Bi-temporal knowledge graph substrate (P1)

- [x] (P0) Define entity + relationship types (generic: Entity, Relation, with typed edges)
- [x] (P0) Implement graph storage co-located with the memory store
- [x] (P0) Implement edge bi-temporality (relationships also have valid-time)
- [x] (P1) Implement contradiction detection: new fact vs existing fact on same (entity, attribute)
- [x] (P1) On contradiction → invalidate old (close valid_to), insert new, link them (supersedes edge)
- [x] (P1) Implement graph traversal API for retrieval expansion (n-hop, typed)
- [x] (P1) Implement graph centrality as a significance input (well-connected facts matter more)
- [x] (P2) Entity resolution / dedup (same entity referred to differently)
- [x] (P2) Subgraph extraction for a given matter/namespace/scope
- [x] (P3) Graph snapshot at an arbitrary `as_of` time (full historical graph reconstruction)

---

## Phase 5 — Reconstruction & reconsolidation engine (P1, the Shibahama moment)

- [x] (P0) Define the reconstruction trigger: recall of a flagged stale-but-significant memory
- [x] (P0) Implement the gate — reconstruction NEVER fires automatically as a side effect of a plain read
- [x] (P1) Implement re-validation hooks: re-read source (file/tool/graph) or surface to caller for confirmation
- [x] (P1) Implement quarantine: proposed updates enter at LOWER credence, tagged, not promoted
- [x] (P1) Implement corroboration rule: promotion needs a 2nd consistent observation / human confirm / high-credence source
- [x] (P1) Implement invalidate-not-overwrite on the superseded version (preserve history)
- [x] (P1) Emit reconstruction events to the log (so the Tideline can show the moment)
- [x] (P2) Configurable re-validation strategies per provenance type
- [x] (P2) Rate-limit / cost-cap reconstructions so a query storm can't trigger mass re-validation
- [x] (P3) Async/background reconstruction option (validate-on-idle for known-stale significant facts)

---

## Phase 6 — Ingestion gate & poisoning resistance (P1, OWASP ASI06)

- [x] (P0) Implement `write(event)` ingestion path with mandatory provenance
- [x] (P0) Assign credence on ingest based on source kind (agent/web/tool default to lower)
- [x] (P1) Quarantine model-generated and web-sourced content at low credence by default
- [x] (P1) Enforce: low-credence items can never outrank authoritative ones in retrieval
- [x] (P1) Bound auto-consolidation/summarisation to limit semantic drift (cap re-summarisation depth)
- [x] (P1) Treat the memory store as an untrusted input surface — sanitise/validate on read of stored instructions
- [x] (P2) Separate "facts" from "instructions" so retrieved memory can't inject directives
- [x] (P2) Anomaly flags: sudden burst of contradictory writes, suspicious provenance
- [x] (P2) Per-item audit trail of all credence/tier changes with cause
- [x] (P3) Optional signed provenance (write attribution that can't be forged)

---

## Phase 7 — Public API & developer experience (P1, DX is priority #1)

### API surface
- [x] (P0) Finalise the small API: `write`, `recall`, `reinforce`, `why`, `timeline`
- [x] (P0) Make `why(memory_id)` first-class: full significance/tier/provenance/currency trace
- [x] (P1) Stable error types with actionable messages
- [x] (P1) Config object with sane defaults (decay half-life, thresholds, tier budgets)
- [x] (P1) Streaming/iterator recall for large result sets
- [x] (P2) Async API surface (tokio) alongside sync

### Python bindings (`pip install shibahama`)
- [x] (P0) Set up PyO3 + maturin build
- [x] (P0) Expose the full API with Pythonic types and type stubs (.pyi)
- [ ] (P0) Publish a working `pip install` from TestPyPI, then PyPI
- [x] (P1) Async support that plays well with asyncio
- [x] (P1) Integration shim for a popular agent framework (LangChain/LlamaIndex memory interface)
- [x] (P2) Pandas/Arrow export of memory state for analysis

### TypeScript / Node bindings (`npm install shibahama`)
- [x] (P0) Set up napi-rs build
- [x] (P0) Expose the full API with TS types
- [ ] (P0) Publish a working `npm install`
- [x] (P1) ESM + CJS dual package
- [x] (P2) Integration shim for a JS agent framework

### CLI
- [x] (P1) `shibahama` CLI: init a store, write, recall, why, inspect, export
- [x] (P1) `shibahama serve` — start the optional server mode
- [x] (P2) Pretty terminal output for `why` (a text version of the Tideline trace)

---

## Phase 8 — Optional server mode (P2)

- [x] (P1) Implement a thin HTTP/gRPC server wrapping the same core API
- [x] (P1) Namespace/scope isolation (multi-agent, multi-project)
- [x] (P1) AuthN/AuthZ stub (API keys; pluggable for the legal variant)
- [x] (P2) Per-namespace config + quotas
- [x] (P2) Metadata-only request logging (who/when/cost, never content — matters for legal reuse)
- [x] (P2) Health/readiness endpoints + graceful shutdown
- [x] (P3) Horizontal-scale story (sharding by namespace)

---

## Phase 9 — The Tideline (visual debugger, P1 centrepiece)

### Plumbing
- [x] (P0) Define a read-only event/state stream API the UI consumes (replay + live)
- [x] (P0) Scaffold the TS/React app (Vite), connect to core via server mode or a local bridge
- [x] (P1) Session recording format so a run can be saved and replayed in the UI
- [x] (P1) Time-scrubber control (play/pause/seek over a session timeline)

### Views
- [x] (P1) Tier map: memories as nodes, positioned by significance, coloured by tier
- [x] (P1) Live drift animation: nodes move hot→warm→cold and snap back on access
- [x] (P1) "Why did I get this?" panel: click a recalled memory → full `why()` trace
- [x] (P1) Significance breakdown viz: decay curve + reinforcement events over time for one item
- [x] (P1) The Shibahama-moment view: old fact invalidating, quarantined new fact entering at lower credence
- [x] (P2) Poisoning view: quarantined/low-credence items visually walled off; show they can't outrank
- [x] (P2) Bi-temporal scrubber: "show me the memory state as of date X"
- [x] (P2) Graph view: entities + relationships with valid-time edges
- [x] (P3) Diff view between two points in a session
- [x] (P3) Export a view as the README GIF / shareable clip

---

## Phase 10 — Proof: benchmarks (P1/P2)

### Harness
- [x] (P0) Build a benchmark harness (Python) that drives Shibahama, Mem0, and Zep through identical tasks
- [x] (P0) Implement adapters for Mem0 and Zep so comparisons are apples-to-apples
- [x] (P1) Deterministic seeds + logged configs so results are reproducible
- [x] (P1) Metrics: recall accuracy, retrieval token cost, latency, stale-answer rate

### Existing suites
- [ ] (P1) Wire up LoCoMo and run all systems
- [ ] (P1) Wire up LongMemEval and run all systems
- [x] (P1) Build a long-horizon coding-agent memory task (the headline scenario)
- [x] (P1) Produce a results table (accuracy vs token-cost frontier) for the README
- [ ] (P2) Ablations: significance on/off, reconstruction on/off, graph on/off — isolate what each contributes

### CurrencyBench (P2/P3, the defensible new artifact)
- [x] (P2) Design `CurrencyBench`: long-horizon task that injects fact CHANGES mid-stream
- [x] (P2) Metrics: stale-answer rate, time-to-correction after a fact changes
- [ ] (P2) Run all systems; show the gap Shibahama is built to win
- [x] (P3) Write up CurrencyBench as its own `benchmarks/currencybench/README.md` for citability
- [x] (P3) Release the CurrencyBench dataset/generator so others can reproduce

---

## Phase 11 — Headline demo: the long-lived coding agent (P1)

- [x] (P0) Build a minimal coding agent that uses Shibahama as its memory
- [x] (P1) Seed it with a realistic multi-session repo history (decisions, rejections, file moves)
- [x] (P1) Scenario A: agent does NOT re-suggest a previously rejected approach (credence floor working)
- [x] (P1) Scenario B: agent re-validates a moved/renamed file before citing it (reconstruction working)
- [x] (P1) Record the run so it replays in the Tideline (the demo GIF source)
- [x] (P2) Side-by-side: same agent on a warehouse baseline failing both scenarios
- [x] (P2) Package as a runnable `examples/coding-agent/` anyone can `clone && run`

---

## Phase 12 — Testing & correctness (P0/P1, cross-cutting)

- [x] (P0) Unit tests for the data model, bi-temporal invariants, tier transitions
- [x] (P0) Property test: no operation ever deletes a memory (the core invariant)
- [x] (P0) Property test: invalidated facts never appear in default (valid-now) recall
- [x] (P1) Property test: low-credence items never outrank authoritative on identical similarity
- [x] (P1) Significance determinism test: same access history → same significance breakdown
- [x] (P1) Reconstruction gate test: a plain read never mutates memory
- [x] (P1) Crash-recovery test: kill mid-write, reopen, state is consistent
- [x] (P1) Binding parity tests: Python and Node return equivalent results to the Rust core
- [x] (P2) Fuzz the ingestion path (malformed/adversarial writes)
- [x] (P2) Soak test: long-running agent over 10k+ sessions, assert no unbounded growth in hot tier
- [x] (P2) Poisoning red-team test: attempt to promote a planted false fact, assert quarantine holds

---

## Phase 13 — Performance & hardening (P2)

- [x] (P1) Benchmark recall latency (p50/p95) and set a budget
- [x] (P1) Ensure no global scan exists anywhere on the hot path (lazy everything)
- [x] (P2) Profile and optimise the significance recompute path
- [x] (P2) Memory-footprint budget for embedded mode (must stay modest to justify "embeddable")
- [x] (P2) Concurrency: safe multi-reader / single-writer (or MVCC) story, tested
- [x] (P3) SIMD / batched vector ops where the index backend allows
- [ ] (P3) Optional mmap for cold-tier compressed store

---

## Phase 14 — Docs inside the repo (P1, minimal but essential)

- [ ] (P0) Deep `README.md`: thesis, the closed-loop diagram, quickstart, benchmark table, debugger GIF (README IS the paper)
- [x] (P1) `docs/architecture.md`: components, data model, request lifecycle
- [x] (P1) `docs/concepts.md`: significance, tiers, credence, reconstruction explained plainly
- [x] (P1) API reference generated from doc-comments (rustdoc + typedoc + Python docstrings)
- [x] (P1) `examples/` with runnable snippets per binding
- [x] (P2) `docs/benchmarks.md`: methodology + how to reproduce
- [x] (P2) `docs/security.md`: the ASI06/poisoning posture and what is/ isn't guaranteed
- [x] (P2) ADR index kept current
- [x] (P3) A short `docs/why-shibahama.md` telling the rakugo story + the design philosophy

---

## Phase 15 — Launch (P1/P2)

- [ ] (P0) Tag a real `v0.1.0`, publish crate + pip + npm
- [ ] (P1) Record the README demo GIF from the Tideline
- [x] (P1) Write the Show HN post (lead with the embeddable-core + the "remembers why you said no" hook)
- [x] (P1) Prepare a FAQ for the predictable HN objections (null hypothesis, "isn't this just a cache", security)
- [x] (P2) A short launch blog post / writeup (optional, README may suffice)
- [ ] (P2) Reach out for early users / collect first issues
- [ ] (P3) Submit CurrencyBench writeup somewhere citable

---

## Phase 16 — Bridge to the legal-tech variant (P3 here; full scope in its own PRD)

- [x] (P2) Confirm the encryption-at-rest trait and metadata-only logging hooks are in place
- [x] (P3) Confirm forgetting can be globally disabled in favour of flag-for-reverification (config switch)
- [x] (P3) Confirm credence taxonomy is swappable (generic OSS names → firm-authoritative/etc.)
- [x] (P3) Stub the sanitising-gateway integration point (where tokenisation will sit) without building it here
