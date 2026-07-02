# Shibahama — remaining release blockers, proof work, and learned memory-policy work

This file is the single follow-up list after the old implementation `TODO.md` was
reconciled and removed. Parts 1-3 are done. Part 4 is read-only learned-policy
gates: offline evaluation, disabled Stage 2 shadow planning, Stage 3 readiness
checks — no runtime learned policy, no training loop.

This revision adds the **proof and hardening work** identified in the June 2026
state-of-the-repo audit. The earlier file tracked *what was built* and *what is
blocked on external auth*. It did not track the gap that decides whether the repo
reads as serious systems work or a well-built toy: **the thesis is largely
unproven by committed numbers, and a few claims are staged rather than real.**
That work is sequenced below as Gate 0 → Phase A → Phase B → Phase C, ahead of
the existing release/RL items, because none of the publishing or RL work matters
if the core claims don't hold up under a sharp reviewer.

Keep the core ethos intact throughout: never-delete invariant, credence floor,
usage-driven significance, and DX/legibility as priority #1. Nothing here may
violate never-delete.

Status legend: `[ ]` open · `[x]` done · `[!]` blocked on external auth/account
action · `[~]` partially done / staged.

Priority: **P0** = a reviewer catches this / it blocks a clean clone · **P1** =
required for a credible proof or launch · **P2** = strong differentiator · **P3**
= polish / stretch.

Strategic frame (decided): primary users are **coding-agent memory** and **agent
framework builders**. This deliberately pulls the benchmark emphasis away from
conversational-recall leaderboards (LoCoMo/LongMemEval) and toward (a) the Rust
performance story and (b) a differentiated continuity/epistemic eval the field
does not currently measure. Standard benchmarks are done last, as hygiene, not as
the headline.

### Spec documents (read these for the buildable detail)

The phase items below are the checklist. The full buildable specs — dataset
schemas, metric formulas, adapter interfaces, acceptance criteria — live in
separate documents. When working a phase, read its spec first:

- **Phase A** → `docs/specs/PHASE-A-performance.md` (perf harness, scale tiers,
  metric JSON shape, post-write-availability gate)
- **Phase B** → `docs/specs/PHASE-B-continuity.md` (ContinuityBench dataset,
  exact metric definitions, adapter interface, Engram guardrail) — **the wedge;
  read this in full before touching item 28**
- **Phase C** → `docs/specs/PHASE-C-standard-benchmarks.md` (LoCoMo/LongMemEval
  artifacts, honesty requirements, cross-reference to Phase B)

---

## Gate 0 — Correctness & clean-clone fixes (do FIRST, blocks everything)

Each of these is something a reviewer reading the code will catch, and several
touch the exact mechanisms Phase B will benchmark. The epistemic eval cannot be
credible while the significance engine has a known double-penalty bug. Close this
gate before Phase A.

18. [ ] (P0) Document the precise never-delete invariant in an ADR. Invalidation
    currently deletes secondary vector/embedding rows but not memory rows —
    `core/src/storage.rs:2974-2993`. This is defensible (embeddings are derived
    and regenerable) but the gap between the "never delete" claim and the code
    must be stated explicitly: "source/event data is immutable; derived indices
    are regenerable." Either tombstone embeddings too, or write the ADR — do not
    leave the claim broader than the implementation.
19. [ ] (P1) Decide and document the recall-scoring defaults. Recency weight and
    graph weight both default to `0.0` — `core/src/retrieval.rs:182-203` — so the
    two mechanisms that make Shibahama distinct contribute nothing to ranking by
    default. Either flip them on (preferred, makes the thesis true by default) or
    write an ADR explaining why they ship off. Phase B depends on this being
    resolved.
20. [ ] (P1) Resolve the staged graph-in-recall claim. Recall does not use the
    stored graph; it only expands through a caller-supplied `RelatedMemoryProvider`
    and the bench feeds it a hand-built map — `core/src/retrieval.rs:503-539`,
    `benchmarks/shibahama_bench/adapters.py:86-124`. Either wire stored-graph
    traversal into recall (honest fix, preferred for the coding-agent story where
    "files/symbols relate to each other" is the use case) or stop claiming
    graph-aware recall in README/docs. Phase B's contradiction/relatedness slice
    needs the real graph.
21. [ ] (P1) Replace the one production `expect()` that can panic if the action
    list drifts — `core/src/learned_policy.rs:469-481`. Convert to a recoverable
    error; add a test for the drift case.

## Phase A — Performance proof (Rust strength, no LLM, fully under our control)

> **Spec: `docs/specs/PHASE-A-performance.md`** — read before starting. Items
> 22–27 below map to its deliverables and acceptance criteria.

The Rust-first thesis is a performance claim that currently has zero committed
numbers. This is the fastest, lowest-risk path to a defensible result and it
directly counters the funded competition's known weakness: graph-construction
systems are expensive and slow to make new memories retrievable. For coding
agents specifically, **write-then-immediately-recallable at sub-millisecond local
latency** is the property they need — a coding agent that just learned a fact
cannot wait for background graph processing. Make that property a number.

22. [ ] (P1) Build a criterion-based benchmark harness in `benchmarks/perf/`
    (Rust, `criterion`). Measure, at minimum: write latency, recall latency
    p50/p99, ingest throughput (items/sec), and post-write recall availability
    (is a just-written item recallable on the next call — yes/no + latency).
23. [ ] (P1) Run the suite at scale tiers: 1k / 10k / 100k / 1M items. Report
    recall p50/p99 and resident memory footprint at each tier. Commit the raw
    output + a generated Markdown table under `benchmarks/results/perf/`.
24. [ ] (P1) Capture HNSW recall quality vs latency tradeoff (recall@k against an
    exact-search ground truth) so the speed numbers are not divorced from
    accuracy. A fast index that returns wrong neighbours is not a win.
25. [ ] (P2) Add a "cold vs warm vs hot tier" latency breakdown — show that the
    tier model actually buys something (hot recall is faster than cold-content
    rehydration). This makes the tiering thesis measurable, not just asserted.
26. [ ] (P2) Document the bench environment (CPU, RAM, OS, rustc version, commit
    hash, seed, exact command) alongside every result file. Numbers without a
    reproduction recipe are not proof.
27. [ ] (P3) Add a CI job that runs a small perf smoke (1k items) and fails on
    gross regression (e.g. p99 recall > threshold), so performance can't silently
    rot.

## Phase B — Differentiated continuity / epistemic-governance eval (THE WEDGE)

> **Spec: `docs/specs/PHASE-B-continuity.md`** — read in full before item 28.
> It holds the dataset schema, the exact metric definitions (stale-answer rate,
> contradiction-resolution accuracy, credence-tracks-evidence ρ, token cost), the
> system-agnostic adapter interface, and the Engram guardrail. This is the phase
> most likely to drift if built from the checklist alone.

This is where Shibahama wins rather than ties. The field openly admits it does
**not** evaluate what happens after retrieval — contradiction resolution,
staleness detection, and whether confidence tracks evidence quality. Those are
exactly Shibahama's mechanisms (credence, bi-temporal staleness, usage-driven
significance, non-destructive supersession). Build a reproducible benchmark that
measures them, framed in the language of **coding agents**: stale API signatures,
renamed functions, changed dependency versions, reversed decisions.

NOTE: Engram (`arXiv:2606.09900`) is the closest published comparison
(bi-temporal, non-destructive supersession, provenance chains). Per the existing
competitive-proof item, **do not imply Shibahama is ahead until a checked-in
artifact proves a stale-rate, auditability, or token-cost win on a matching
continuity slice.** This phase is where that artifact gets produced — or where we
honestly report that it doesn't beat Engram and adjust the claim.

28. [ ] (P1) Design `ContinuityBench` (extends the existing CurrencyBench idea
    past 12 hand-built queries into a real, larger, documented dataset). Each
    task: a fact is established, the fact CHANGES over time (supersession), and a
    later query must reflect the current state. Coding framing: "what's the
    signature of `foo()`" after `foo` was renamed/re-typed across sessions.
29. [ ] (P1) Define and report the metrics the field doesn't:
    - **stale-answer rate**: fraction of queries answered with a superseded fact.
    - **contradiction-resolution accuracy**: when two memories conflict, does the
      system surface the one with higher credence / more recent valid-time?
    - **credence-tracks-evidence**: correlation between an item's credence and the
      quality of its provenance/corroboration.
    - **retrieval token cost** per query (the economics axis — a continuity win is
      an economics win before a raw-accuracy win).
30. [ ] (P1) Report HONEST baselines: flat/warehouse retrieval, full-context where
    reproducible, and at least one real external system (Mem0 OSS self-hosted,
    and Engram if runnable). Report cases where the flat baseline wins on plain
    one-shot accuracy — owning that is more credible than hiding it, and it's the
    point of `docs/null-hypothesis.md`.
31. [ ] (P1) Every result file carries: dataset hash, model, seed, exact command,
    and the baseline configs. Commit JSON + generated Markdown under
    `benchmarks/results/continuity/`.
32. [ ] (P2) Tideline integration: a view that *shows* a stale answer being
    avoided — the superseded item, the current item, the credence/valid-time that
    decided it, with the `why` trace. This is the headline DX moment for the
    wedge; the legible version of contradiction resolution nobody else has.
33. [ ] (P2) Add a small "epistemic governance" coding-agent demo script under
    `examples/` that an interviewer can run in under a minute and watch a stale
    API fact get correctly superseded.

## Phase C — Standard benchmarks (table-stakes hygiene, done honestly, LAST)

> **Spec: `docs/specs/PHASE-C-standard-benchmarks.md`** — read before running.
> It defines the required baselines, honesty requirements, the external-anchor
> (Mem0 OSS) requirement, and the Phase-B cross-reference that tells the full
> story.

Their absence is a guaranteed interview question ("why no LoCoMo number?"); their
presence is not the differentiator. Goal: "we score competitively and our harness
is fully reproducible," not "we win." Loaders already exist; artifacts are
pending.

- [!] (P1) Run LongMemEval-S and LoCoMo from official exports and commit
      generated JSON + Markdown artifacts. Reports must include flat/warehouse
      baselines, full-context or published-system comparison where reproducible,
      retrieval token cost, stale-answer rate where applicable, dataset hash,
      model, seed, and exact command.
      (Carried forward; loaders exist at `docs/benchmarks.md:119-125`, artifacts
      pending per `NEXT-TODO.md:36-40` of the prior file.)
34. [ ] (P1) Add at least one real external system to the comparison rather than
    only the strawman warehouse baseline (which scores 0 and reads as rigged). A
    self-hosted Mem0 OSS run on the same continuity slice is the minimum credible
    external anchor.
35. [ ] (P2) Cross-reference Phase C results against Phase B: explicitly state
    where Shibahama is competitive on standard recall and where it wins on
    stale-rate/economics. The pair is the honest story.

## Bindings & API surface hardening

The bindings are real (PyO3 / napi-rs) but parity is smoke-level only and the
binding crates have 0 Rust tests — a reviewer comparing "Python/Node bindings"
the claim against the tests will find this fast.

36. [ ] (P1) Build a golden-vector parity suite: a fixed set of write+recall
    sequences with committed expected outputs, run identically against the Rust
    core, the Python binding, and the Node binding, asserting identical recall
    ordering and significance/credence values. This is a strong correctness
    signal and closes the "are the bindings actually equivalent" gap.
    Current state: Python↔Node smoke only at
    `scripts/ci/correctness-smoke.py:123-170`; no Rust-core↔binding parity suite.
37. [ ] (P2) Add the missing HTTP endpoints for a complete surface: a standalone
    `/timeline` route and graph CRUD, so the server mirrors the full
    write/recall/why/timeline/audit/graph API rather than most of it
    (`shibahama-cli/src/main.rs:980-998`).
38. [ ] (P3) Add a minimal Rust integration test per binding crate so they are not
    at zero coverage.

## External release blockers (carried forward — blocked on external auth/account)

- [!] Publish a working `pip install shibahama` from TestPyPI, then PyPI —
      blocked on TestPyPI/PyPI token or trusted publishing setup; local
      build/check helper exists at `scripts/release/python-publish.sh`.
      NOTE: depends on Gate 0 item 17 (clean python build) landing first.
- [!] Publish a working `npm install shibahama` — blocked on npm auth/trusted
      publisher setup; local build/test/pack helper exists at
      `scripts/release/npm-publish.sh`.
- [!] Tag a real `v0.1.0` and publish crate + pip + npm — blocked on
      crates.io/PyPI/npm auth and final release-owner action; local preflight
      helpers exist under `scripts/release/`.
- [!] Submit the CurrencyBench/ContinuityBench writeup somewhere citable —
      blocked on archive account/release-owner action; `CITATION.cff`,
      `.zenodo.json`, and the submission checklist exist in-repo. Update the
      writeup to ContinuityBench once Phase B lands.

## User-validation blockers (carried forward)

- [!] Get three production or production-like deployments from users with real
      long-lived memory pain. Convert setup friction, wrong recall, stale recall,
      Tideline confusion, and API-shape issues into tracked GitHub issues before
      adding new framework adapters. For the chosen audience, target coding-agent
      and framework-builder users specifically (e.g. a LangGraph adapter user and
      a custom-coding-agent user).

## Positioning (carried forward — already tightened, keep current)

- [x] Tighten README and launch positioning around the three defensible
      differentiators: never-delete invariant + credence floor, append-only human
      signal verbs (`challenge` / `affirm` / `correct` / `pin`), and Tideline
      legibility for reconstruction/consolidation. Do not lead with
      "usage-aware memory" alone; 2026 competitors now claim multi-signal and
      temporal retrieval.
- [x] Add Engram (`arXiv:2606.09900`) to `docs/null-hypothesis.md` and benchmark
      docs as the closest published comparison. Do not imply Shibahama is ahead
      until checked-in artifacts prove a win on a matching continuity slice.
- [ ] (P2) Write a short "vs Mem0 / Zep / Letta / Engram" positioning page that
    places Shibahama on the epistemic-governance / continuity axis rather than the
    conversational-recall-accuracy axis, citing the Phase A + B artifacts. Frame
    for coding agents and framework builders.

---

## Part 1 — Offline consolidation pass ("the dream"), but LEGIBLE (first-class) — DONE
1. [x] Implement a `consolidate()` pass that runs offline / on idle, never on the
   hot recall path; merges/promotes/demotes/flags without deleting or overwriting
   originals (consolidated memories are NEW items linking back to sources).
2. [x] Drive consolidation from significance/usage + credence floor; floored items
   survive unchanged; test asserts this.
3. [x] Emit a consolidation event per decision with a `why` trace.
4. [x] Tideline consolidation view that replays a pass with `why` per decision.
5. [x] Consolidation is idempotent-safe on an unchanged store.

## Part 2 — Human-in-the-loop "challenge" / override (first-class) — DONE
6. [x] API verbs: `challenge` / `affirm` / `correct` / `pin` / `unpin` with the
   credence/quarantine/floor semantics.
7. [x] Every verb is an append-only audit event with actor + timestamp + reason.
8. [x] Tideline surfaces contested items with the human reason alongside machine
   significance.
9. [x] Human signals logged in RL-ready shape but NOT wired to any reward/automatic
   policy; they affect credence/supersession deterministically.
10. [x] Tests: challenge lowers credence and never deletes; pin enforces floor;
    correct routes through quarantine+corroboration; all four emit audit events.

## Part 3 — Confront the null hypothesis HONESTLY — DONE
11. [x] `docs/null-hypothesis.md` states the threat plainly and defines the regime
    where usage-aware reconstructive memory should win (continuity/currency tasks
    measured by stale-answer-rate and token-economics, not one-shot recall).
12. [x] Benchmark story positions CurrencyBench + continuity as home turf; reports
    flat-retrieval baselines honestly even where they win on plain accuracy.
13. [x] README "When NOT to use Shibahama" section (flat RAG is fine for stateless
    one-shot QA).

## Part 4 — Learned policy for memory operations (stretch, gated)

- [x] Document the core tension: dominant RL-for-memory paradigms (Memory-R1,
      DeltaMem, SEARL) often use destructive / answer-correctness-first incentives
      that fight never-delete and credence floor. A rigorous version restricts the
      action space to non-destructive ops and uses a non-gameable reward.
- [x] Stage 1 (gating): OFFLINE policy evaluation on logged human challenges. No
      training loop. If the offline signal isn't there, STOP.
- [x] Stage 2 planning gate: disabled-by-default contextual-bandit shadow planner
      over `SignificanceConfig` weights; proposes bounded deltas only, never
      mutates runtime policy.
- [ ] (P3) Stage 2 runtime experiment: online contextual-bandit learning over the
      existing significance weights. Reward = contest-derived (affirm +, challenge
      -) with task-outcome as secondary, penalised for any floor/pinned violation.
      Ship only if it wins without violating invariants. **Gated on Stage 1
      showing offline signal.**
- [x] Stage 3 readiness gate: fail-closed checklist (GPU/cost plan, dataset card,
      reward ablations, invariant property tests, held-out continuity eval).
- [ ] (P3) Stage 3 actual training (only if 1-2 prove out): small policy model via
      GRPO/PPO over the constrained non-destructive action space. Document infra
      honestly; reward design written up and ablated.
- [ ] (P1 for any stage that runs) Eval requirement: report whether the learned
      policy beats the hand-tuned significance function on a held-out continuity
      task, and PROVE via property test over the action trace that it never
      violated never-delete / floor. No invariant violations is a hard gate, not a
      metric.
- [x] Anti-sycophancy clause: if RL doesn't beat the deterministic baseline, the
      honest outcome is "deterministic significance is sufficient; RL not
      justified" — written up, not buried.

## Reconcile / report back
14. [x] Old `TODO.md` reconciled and removed; shipped work, docs, release blockers,
    and gated learned-policy work folded here.
- [ ] After Gate 0 + Phase A land, re-run the state-of-the-repo audit and update
    the "top reviewer catches" list — the goal is that none of the current five
    (`cargo build --all` fails, Mem0/Zep absent, LoCoMo/LongMemEval absent, recall
    graph is caller-map not stored, binding parity is smoke-only) remain open.
