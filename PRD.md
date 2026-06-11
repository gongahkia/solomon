# Shibahama — Product Requirements Document

**A usage-aware, reconstructive memory engine for LLM agents.**
*The memory layer that remembers why you said no — and re-checks itself before telling you something stale.*

*Flagship project PRD · Draft v0.1 · 11 June 2026*

---

## 0. The name

Shibahama is a classic rakugo story. A man finds a wallet full of gold on the beach at Shibahama. His wife hides it and convinces him he dreamt it, so he sobers up and works. Years later, successful and sober, she reveals the wallet was real all along. The story turns on a memory deliberately suppressed, preserved untouched, and reconsolidated as true at exactly the right moment.

That is the thesis of this project in one story: **nothing is deleted; significance is revealed by time and use; and a memory is re-validated at the moment it is recalled.**

---

## 1. Problem

Every shipping agent-memory system today — Mem0, Letta/MemGPT, Zep/Graphiti, LangGraph store — is, underneath, a **warehouse**: write facts in, retrieve them by similarity, occasionally garbage-collect. This inherits two failures that anyone who has run a long-lived agent has felt:

1. **No currency at recall.** The store will happily surface a fact that was true ten refactors ago. A coding agent confidently cites `auth/session.ts` after it moved to `core/identity/`. Bi-temporal graphs (Zep) record *that* a fact changed, but the burden is on write-time bookkeeping; nothing re-checks a fact against present reality *at the moment it is used*.
2. **No significance signal.** Retrieval ranks on embedding similarity (plus, at best, recency and graph structure). It throws away the single richest signal available: **how memories are actually used.** "This decision has been pulled into 9 of the last 12 sessions" and "the user explicitly rejected this approach once and never revisited it" are exactly the significance cues a human expert relies on — and no incumbent ranks on them, even though every system already logs the access events for free.

The deeper diagnosis (and the reason this is hard, not just unbuilt): **storage is trivially solved; turning storage into trustworthy, current, relevant context is not.** Semantic similarity cannot encode significance or currency. Humans don't solve this by scanning their entire memory on a schedule — they solve it *lazily, at retrieval*, by reconstructing a memory against present context when (and only when) it's actually needed, and by letting unused memories fade in accessibility while important ones strengthen through use.

Shibahama ports that loop to agents — not as a neuroscience cosplay, but because it captures signal the warehouse model discards.

### Non-goals
- Not a vector database (it sits on top of one).
- Not an agent framework (it's a memory engine any framework can embed).
- Not trying to "solve memory perfectly." The explicit stance: a memory system should know *where* facts live, *how current* they are, and *how much* to trust them — then surface that for verification, not pretend to objectivity it lacks.

---

## 2. Thesis: the closed loop

Shibahama's two central mechanisms are not separate features. They are two halves of one loop, and each is incomplete without the other:

```
        access event
             │
             ▼
   ┌──────────────────┐     reinforce on use
   │ USAGE SIGNAL      │────────────────────────┐
   │ (who/when/why/    │     decay on neglect    │
   │  led-anywhere)    │◀────────────────────────┘
   └──────────────────┘
             │ drives
             ▼
   ┌──────────────────┐
   │ SIGNIFICANCE      │  promotes / demotes across tiers
   │ (emergent, not    │  hot ⇄ warm ⇄ cold   (never deleted)
   │  written at       │
   │  ingest)          │
   └──────────────────┘
             │ flags "load-bearing but possibly stale"
             ▼
   ┌──────────────────┐
   │ RECONSTRUCTION    │  on recall of a cold/stale-but-significant
   │ (gated re-        │  memory: re-validate against current reality,
   │  validation at    │  propose update at LOWER credence (quarantined),
   │  recall)          │  never silently mutate  ← the Shibahama moment
   └──────────────────┘
```

- **Usage drives significance:** what gets reinforced vs what decays is a function of access history, not an ingest-time score.
- **Significance drives reconstruction:** the engine only spends the cost of re-validating a memory when significance says it's load-bearing *and* staleness signals say it may have drifted.
- Usage-awareness *without* reconstruction is just better ranking. Reconstruction *without* the usage signal has no principled trigger. Together they close the loop.

---

## 3. The load-bearing design decision: what "decay" physically does

Decay is **tiered demotion, never deletion.** Three tiers, mirroring the OS-memory analogy the field already accepts:

| Tier | State | Cost to surface | Entered by |
|---|---|---|---|
| **Hot** | resident in working context | ~free | high significance + recent use |
| **Warm** | indexed, one retrieval hop | cheap | default for live memories |
| **Cold** | compressed, deliberately expensive to reach | requires explicit reconstruction step | sustained neglect |

- **Decay** = demotion (hot→warm→cold) as the usage signal falls. **Reinforcement** = promotion on access. **Reconstruction** = the gated event when a cold-but-significant memory is pulled back and re-validated against current reality.
- **Nothing is ever deleted.** This is the safety guarantee that makes the project shippable: "my memory tool silently lost data" is the HN comment that kills a launch, and Shibahama structurally cannot produce it. Cold ≠ gone; cold = present but costly, exactly like the suppressed wallet.
- A **credence floor** protects classes of memory from ever decaying below a threshold (user-pinned facts, explicit rejections — "we ripped out Redis sessions, don't suggest it"). Significance can fade; an explicit "no" should not.

Why not the bolder "decay = real eviction-to-loss"? Because it reintroduces the liability we designed out — a coding agent that permanently forgets *why* a weird workaround exists is actively harmful. Why not the safer "decay = pure re-ranking, nothing moves"? Because it isn't novel enough to carry the thesis and gives the debugger nothing to show. Tiered demotion is the synthesis: real movement (novel, demoable) without loss (safe).

---

## 4. Reconstruction & reconsolidation, made safe

The obvious objection: "recall makes a memory editable" is OWASP ASI06 (memory/context poisoning) stated as a design principle. Shibahama defuses this by making reconsolidation **explicit, gated, and quarantined** — never an automatic read-triggers-write:

1. On recall of a memory flagged stale-but-significant, the engine performs a **reconstruction step**: re-validate the fact against current reality (re-read the source file, re-query the live graph, or surface to the caller/human).
2. Any proposed update enters at **lower credence**, quarantined, and is tagged with provenance. It never overwrites the existing fact.
3. Promotion of the updated fact requires corroboration (a second consistent observation, a human confirmation, or a high-credence source).
4. The prior version is **invalidated, not deleted** (bi-temporal: valid-time closed, ingestion-time preserved), so history and audit survive.

This means the dramatic moment — pulling a cold memory back and discovering reality has moved — is also the *safe* moment: it's where currency gets enforced, under guardrails, instead of silently rotting in the store.

---

## 5. Architecture

A **Rust core** (the hot path: tier dynamics, the bi-temporal graph, significance computation, reconstruction gating), embeddable in-process by default (the SQLite-for-agent-memory framing), with an **optional thin server mode** over the same API for multi-agent / team use. **Python and TypeScript bindings**: Python for the agent/ML ecosystem and the benchmark harness; TypeScript for the debugger and JS agent frameworks.

```
┌────────────────────────────────────────────────────────────┐
│  Host agent (any framework: Claude Code, LangChain, custom)  │
└───────────────┬──────────────────────────────┬──────────────┘
                │ write(event)                  │ recall(query, ctx)
                ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│  SHIBAHAMA CORE (Rust)                                         │
│                                                                │
│  ┌────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Ingestion  │  │ Significance     │  │ Retrieval          │  │
│  │ gate       │  │ engine           │  │ orchestrator       │  │
│  │ (attribute,│  │ (usage signal →  │  │ (similarity ⊕ graph│  │
│  │ credence,  │  │  decay/reinforce │  │  ⊕ temporal-now ⊕  │  │
│  │ quarantine)│  │  → tier moves)   │  │  significance)     │  │
│  └────────────┘  └─────────────────┘  └─────────┬──────────┘  │
│                                                  │             │
│  ┌──────────────────────────────────┐  ┌────────▼──────────┐  │
│  │ Bi-temporal store (substrate)     │  │ Reconstruction    │  │
│  │ valid-time + ingest-time + prov.  │  │ engine (gated     │  │
│  │ hot / warm / cold tiers           │  │ re-validation)    │  │
│  │ invalidate-don't-delete           │  └───────────────────┘  │
│  └──────────────────────────────────┘                         │
│            │ pluggable                                         │
│            ▼                                                   │
│  vector index (any: lancedb/qdrant/pgvector)  +  access log    │
└──────────────────────────────┬───────────────────────────────┘
                               │ read-only event stream + state
                               ▼
                  ┌────────────────────────────┐
                  │  THE TIDELINE (debugger UI) │  ← priority #1
                  │  TypeScript / React          │
                  └────────────────────────────┘
```

### 5.1 Core data model
Each memory item carries: `content`, `embedding`, `valid_from` / `valid_to` (bi-temporal), `ingested_at`, `provenance`, `credence_tier`, `significance_score` (derived, mutable), `tier` (hot/warm/cold), `access_log` (timestamps + outcome signal), `credence_floor`.

### 5.2 The significance engine (the novel part)
Significance is **not** stored at ingest. It is recomputed from the access log: a decay function over time since last use, a reinforcement term on each access, a boost when an access *led somewhere* (the agent's next action succeeded / the memory was cited in output), and a penalty for contradiction. Tier transitions are thresholded on this score, with the credence floor as a hard clamp. This is the part no incumbent does, it's free signal, and it's fully inspectable.

### 5.3 API surface (small on purpose)
```
write(event)                    → ingest with attribution + credence
recall(query, context)          → ranked memories w/ provenance + tier + currency flag
reinforce(memory_id, outcome)   → feed the usage signal back
why(memory_id)                  → full significance/tier/provenance trace (powers the debugger)
timeline(query, as_of)          → "what did I believe on date X" (bi-temporal query)
```
`why()` is a first-class API call, not an afterthought — because DX is the #1 proof of quality.

---

## 6. The Tideline (visual debugger) — priority #1

The thing that makes Shibahama *land* is that you can **see memory living**. The Tideline is a real TypeScript/React app, not a notebook.

- **Tier map:** memories as nodes, positioned by significance, coloured by tier; you watch them drift hot→warm→cold and snap back on access, in real time or scrubbed over a session timeline.
- **"Why did I get this?":** click any recalled memory → the full `why()` trace: similarity score, graph path, significance breakdown (decay curve + reinforcement events), credence tier, valid-now status. This is the answer to Zane's whole complaint — significance made legible.
- **The Shibahama moment, visualised:** when a cold-but-significant memory is reconstructed and reality has drifted, the UI shows the old fact invalidating and the quarantined new fact entering at lower credence. This is the demo GIF that goes in the README and the launch tweet.
- **Poisoning view:** quarantined / low-credence items are visually walled off; you can see they cannot outrank authoritative facts.

A reconstructive, decay-driven engine is the *hardest* thing to give good DX to — which is exactly why nailing the debugger is the differentiator. The incumbents win on inspectability because a row is there or it isn't; Shibahama has to *earn* inspectability, and the Tideline is how.

---

## 7. Proof: benchmarks & the headline demo

**Headline scenario — a long-lived coding agent** (relatable to the entire HN audience). The agent works a real repo over many sessions and accumulates decisions: "we use pnpm not npm", "auth lives in `core/identity`", "we tried Redis sessions and ripped them out — don't re-suggest". The two visceral failure modes Shibahama fixes:
- **Re-suggesting the rejected thing** (no significance reinforcement of an explicit "no") → Shibahama's credence floor + significance keeps the rejection load-bearing.
- **Citing a moved/renamed file** (no currency at recall) → Shibahama's reconstruction step re-validates against the current tree before answering.

**Quantitative proof (ranked #2 priority):** evaluate on existing long-horizon memory suites — **LoCoMo, LongMemEval**, and a long-horizon coding-memory task — against Mem0 and Zep. Target claims, to be earned not assumed:
- Equal-or-better recall accuracy at **materially lower retrieval token cost** (the usage signal lets us surface fewer, better memories — the token-efficiency argument is real and measurable in the literature).
- **Lower stale-answer rate** (a currency metric the standard suites under-measure — see below).
- **No global maintenance scans** (decay is lazy/at-access), vs periodic re-summarisation in warehouse models.

**A small new benchmark (ranked #3, optional stretch):** `CurrencyBench` — a long-horizon task that explicitly injects fact *changes* mid-stream and measures stale-answer rate and time-to-correction. This exposes precisely what similarity-only stores miss and what Shibahama is built for. Shipping even a small version of this is itself a citable contribution.

---

## 8. Why this is credible to Anthropic / OpenAI (FDE lens)

- **Systems maturity:** a Rust hot-path core with clean bindings, not a LangChain wrapper — dodges the "it's just glue" dismissal that kills most memory repos.
- **Judgment under tension:** the PRD itself shows the candidate argued *against* the cute idea, found the defensible core (usage-as-signal), and kept the bold mechanism (reconstruction) only after making it safe. FDE work is exactly this: take a customer's enthusiasm, find what actually holds, ship the defensible version.
- **Measurement honesty:** claims are framed as "to be earned," with a currency metric the field under-measures. That's the empiricism these labs screen for.
- **DX obsession:** the Tideline shows the candidate cares about the human using the tool — the core of forward-deployed work.

---

## 9. Milestones (multi-month flagship)

| Phase | Duration | Output |
|---|---|---|
| **M0 — Spike** | 2–3 wks | Rust core: bi-temporal store + tiers + naive significance; Python binding; write/recall/why working in a REPL. |
| **M1 — The loop** | 3–4 wks | Significance engine (decay/reinforce/outcome), gated reconstruction + quarantine, credence floor. Closed loop demonstrable on a toy coding-agent log. |
| **M2 — The Tideline** | 3–4 wks | TS/React debugger: tier map, `why()` trace, the Shibahama-moment visual. This is the centrepiece; budget accordingly. |
| **M3 — Proof** | 3–4 wks | Benchmark harness vs Mem0/Zep on LoCoMo + LongMemEval + coding task; CurrencyBench v0; results table in README. |
| **M4 — Launch** | 1–2 wks | Deep README (the README *is* the paper: thesis, architecture, benchmark table, debugger GIF), `cargo`/`pip`/`npm` packaging, HN/Show HN post. |

---

## 10. Risks & honest limitations

- **Null hypothesis:** decay/reinforcement may just be a worse cache-eviction policy in a neuroscience costume. **Mitigation:** the benchmark must show it beats similarity+recency baselines on a currency metric, or the thesis is wrong and we say so. The framing leads with *usage-as-signal* (defensible without neuroscience), not "brain-inspired."
- **Forgetting the wrong thing:** mitigated structurally — nothing deletes, credence floor protects explicit signals.
- **Reconstruction as attack surface:** mitigated by gating + quarantine + corroboration (Section 4).
- **DX of an emergent system is hard:** acknowledged as the central engineering challenge; it's also the differentiator, so the budget reflects it.
- **Tuning the significance function** is real research; ship a transparent, hand-tuned version first, learn the weights only if data justifies it (earn complexity).
