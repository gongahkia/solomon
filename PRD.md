# Solomon — Product Requirements Document

**A good-law engine for your firm's own knowledge.**
*Every law firm checks whether a published case is still good law. Nobody checks whether the firm's own positions, precedents, and advice are still good law. Solomon does — behind a zero-retention boundary.*

*Legal-tech flagship PRD · Draft v0.1 · 11 June 2026*

---

## 0. The name

Solomon — for the judgment to weigh what a thing is *worth* and whether it still *holds*. The system does not decide the law; it surfaces what the firm knows, how current it is, and what it depends on, so a human can judge. The name signals discernment, not automation.

---

## 1. The one-sentence wedge

**Solomon applies Shepard's-style currency reasoning to a firm's *internal* knowledge — its positions, precedents, house views, and prior advice — behind a boundary where that knowledge never leaves the firm's perimeter.**

External-citation currency (is *this published case* still good law?) is solved by Shepard's, KeyCite, Lexis Protege, JurisCheck. Solomon does not touch that. The unoccupied gap is currency of the firm's *own* knowledge: is *our* position still valid, what superseded it, and what does it depend on that may have moved.

---

## 2. Problem

### 2.1 The market's own words
The legal-AI market has named Solomon's problem without building it. A 2026 Thomson Reuters piece describes an emerging firm role — the "knowledge operations curator" — whose job is to maintain the firm's internal source of truth *so the AI doesn't confidently resurrect a brief from 2014 that cites a law that was nullified in 2019*. That is, verbatim, the failure Solomon prevents — but the market's answer is to hire a person to do it manually, because no tool tracks internal currency.

Meanwhile the documented harm is exploding: by April 2026 there were well over a thousand tracked cases of AI-hallucinated or stale citations reaching courts, with sanctions, fines, and a Sixth Circuit penalty for fabricated citations. The dangerous failure mode the research keeps flagging is not the fabricated case — it's the *real authority that was later overruled, narrowed, or whose underlying rule changed*. It is subtler, harder to catch, and "more dangerous than fabricating a case outright" because a positive surface signal stops verification too early.

### 2.2 Why current legal KM doesn't solve it
Firm knowledge management in 2026 is crowded — a majority of top firms have deployed AI KM — but every offering (Harvey, Spellbook, Clio, Sysero, NexLaw) does the same three things: semantic search, automated metadata tagging, and precedent retrieval. They treat firm knowledge as a **timeless warehouse with good search**. Newer, better-tagged storage. None of them model **temporal truth**: that a memo true in 2023 may be false in 2026 because something it depended on changed. They will confidently return the most *similar* document, never the most *currently-valid* one.

### 2.3 The two compounding constraints
1. **Currency, not relevance, is the hard problem for internal knowledge.** A 2019 position isn't less significant because it's old — it's either still live or it's been superseded, and that's a *truth* question.
2. **The knowledge cannot leave the perimeter.** Firm positions and client advice are confidential and often privileged. Feeding them to a model under conventional retention is exactly the exposure that ZDR procurement and the privilege-waiver risk are about. So the currency engine must operate behind a sanitising boundary.

No tool addresses (1). No tool addresses (1) *and* (2) together. That intersection is Solomon.

---

## 3. The product split — how Solomon is visibly distinct (read this if you only read one section)

Solomon is one system with three separable layers. The distinction is not cosmetic; each layer answers a different production question:

| | Question it answers | Competency it proves | Memory stance | Stack |
|---|---|---|---|---|
| **Boundary** | What is safe to let leave the building? | Regulated safety infrastructure | **Stateless** — forgets by design | Python/FastAPI |
| **Currency engine** | Is what we know still true, and can we prove it? | Domain reasoning under constraints | **Never forgets** — currency is the problem | Python |
| **MCP/API layer** | How do existing legal-AI tools ask for current firm context? | Infra-grade integration surface | **Just-in-time** — injects only scoped, current context | MCP, HTTP API, thin CLI |

The boundary is a native Solomon subset, not a separate product. The currency engine is the source of truth. The MCP/API layer is the primary product surface: Claude, Copilot, Harvey-like vendors, iManage-style knowledge systems, and internal tools should call Solomon for preflight context, currency checks, impact analysis, verification writes, and audit packs. A standalone curator console exists only as a thin side-channel for human review; it is not the destination app and it does not replace the legal tools lawyers already use.

Solomon rejects age/usage decay because currency, not significance-fade, is the legal problem.

---

## 4. What the boundary owns vs what the currency engine owns

Solomon includes a production sanitising boundary: deterministic PII/MNPI detection across 18 jurisdictions, statute-cited, with a reversible `/pseudonymize` ↔ `/reidentify` round-trip, volatile mapping storage, document scrub, and offline-default packaging. Solomon treats it as the **boundary layer** and builds the **currency layer** on top.

| Concern | Source |
|---|---|
| Outbound sanitisation / tokenisation before any model call | **Boundary** `/pseudonymize` |
| Inbound demasking of model responses | **Boundary** `/reidentify` |
| Ingestion safety gate (is this safe to store / does it contain MNPI) | **Boundary** `/review` |
| Volatile mapping and document scrub | **Boundary** |
| Local vs server deployment, offline SKU | **Solomon** |
| Bi-temporal knowledge store (valid-time / ingestion-time) | **Solomon — new** |
| Dependency graph (internal knowledge → external authority) | **Solomon — new** |
| Currency engine (is this still good law for us?) | **Solomon — new** |
| Credence ledger + verification step | **Solomon — new** |
| Supersession / contradiction reasoning | **Solomon — new** |

The boundary is solved. The currency engine is the project.

---

## 5. Center of gravity (ranked, per the build priorities)

1. **Bi-temporal currency / good-law engine** — the core. Internal knowledge with valid-time and ingestion-time; supersession instead of deletion; the ability to answer "is this still live, and if not, what replaced it."
2. **Credence + verification** — every surfaced position carries a trust tier and a verification state; nothing load-bearing is asserted without a source pointer and a "last verified" timestamp.
3. **Audit / privilege evidence chain** — defensible proof of *what the firm knew, when, on what basis, and what verification occurred* — the artifact that survives a challenge.
4. **Boundary round-trip** — native review, pseudonymize, reidentify, scrub, and fail-closed egress handling.

---

## 6. Architecture

A Python system inside the firm perimeter. Durable knowledge never leaves; only Solomon-sanitized, just-in-time context crosses to a model endpoint that retains nothing. Dual endpoint: a remote ZDR provider for power, a local in-perimeter model for strict matters — the routing decision is part of the system.

```
┌──────────────────────────────────────────────────────────────────────┐
│  FIRM PERIMETER                                                        │
│                                                                        │
│  Lawyer ──query──▶ ┌────────────────────────────────────────────┐     │
│                    │ SOLOMON                                     │     │
│                    │                                             │     │
│                    │  ┌───────────────┐   ┌──────────────────┐   │     │
│                    │  │ Currency      │   │ Dependency graph │   │     │
│                    │  │ engine        │◀─▶│ internal know-   │   │     │
│                    │  │ (good-law for │   │ ledge → external │   │     │
│                    │  │  firm know.)  │   │ authority edges  │   │     │
│                    │  └───────┬───────┘   └──────────────────┘   │     │
│                    │          │                                  │     │
│                    │  ┌───────▼────────┐  ┌──────────────────┐   │     │
│                    │  │ Bi-temporal    │  │ Credence ledger  │   │     │
│                    │  │ knowledge store│  │ + verification   │   │     │
│                    │  │ valid/ingest   │  │ state per fact   │   │     │
│                    │  │ supersede≠del  │  └──────────────────┘   │     │
│                    │  └───────┬────────┘                         │     │
│                    │          │ retrieved context                │     │
│                    │          ▼                                  │     │
│                    │  ┌────────────────────────────────────┐     │     │
│                    │  │ Solomon boundary client             │     │     │
│                    │  │ /review (ingest gate)               │     │     │
│                    │  │ /pseudonymize (out) /reidentify(in) │     │     │
│                    │  └───────────────┬────────────────────┘     │     │
│                    │                  │ sanitised tokens only    │     │
│                    │  ┌───────────────▼────────────────────┐     │     │
│                    │  │ Audit journal (append-only)         │     │     │
│                    │  └─────────────────────────────────────┘    │     │
│                    └──────────────────┬──────────────────────────┘     │
│                                       │ sanitised, ephemeral ctx       │
└───────────────────────────────────────┼────────────────────────────────┘
                                        │
                      ┌─────────────────▼─────────────────┐
                      │ Model endpoint (stateless, ZDR)   │
                      │  • remote ZDR provider (power)    │
                      │  • local in-perimeter (strict)    │
                      └───────────────────────────────────┘
```

### 6.1 The currency engine (core)
- Internal knowledge items (positions, clauses, house views, advice) stored bi-temporally: `valid_from`, `valid_to`, `ingested_at`, `provenance`.
- Each item may declare **dependencies** on external authorities (a statute §, a regulation, a case) and on **other internal items** (this position relies on that memo).
- When a dependency changes (external authority amended/overruled, or an internal item superseded), every item depending on it is flagged **stale-pending-reverification** — *not* invalidated automatically (that would be a truth claim the system can't make), and *not* deleted.
- Querying returns currently-valid items by default, each annotated with: currency state (live / stale-pending / superseded), what it depends on, and what (if anything) superseded it.

### 6.2 Dependency graph (the technically interesting part)
The novel structure: a graph where firm knowledge hangs off the things it relies on. This is what lets Solomon answer "the regulation under our 2023 advice changed — show me everything that now needs re-checking" — a query no warehouse KM can answer because it has no edges, only similarity.

### 6.3 Credence + verification
- Tiers: firm-authoritative (partner-signed) / verified / model-inferred / unverified.
- Every item carries a `last_verified_at` and `verified_by`. Currency is a function of (validity of dependencies) × (staleness of verification).
- A verification step surfaces the source pointer before any load-bearing output and refuses to let model-inferred items outrank firm-authoritative ones.

### 6.4 Boundary
- Ingestion → `/review` gate (flag MNPI, attribute, refuse unsafe).
- Any context assembled for a model call → `/pseudonymize` before egress; response → `/reidentify`.
- Routing: matter sensitivity decides remote-ZDR vs local model. Strict matters never egress even sanitised.

### 6.5 Audit chain
Append-only journal: what was known, when, on what basis, what verification ran, what crossed the boundary (metadata only). This is the privilege/defensibility artifact.

---

## 7. Headline demo — the stale house-view

A reproducible, scripted scenario that dramatises currency-of-internal-knowledge:

1. **2023:** firm issues a house-view memo — "structure X is compliant under \[Regulation R §12]" — and relies on it advising Client A. Solomon stores the memo, its dependency on R §12, and the matter link.
2. **2025:** Regulation R is amended; §12 changes. Solomon ingests the change (via a feed or manual entry), the dependency graph propagates a **stale-pending-reverification** flag to the house-view memo and to the Client A advice that relied on it.
3. **2026:** an associate asks "what's our position on structure X for a new client?"
   - **Warehouse KM baseline (Harvey/Spellbook-style):** returns the 2023 memo as the top semantic match, confidently, with no staleness signal.
   - **Solomon:** returns the same memo but flagged — *depends on R §12, which changed 2025-xx; not re-verified since; last relied on in the Client A matter; recommend re-checking before use* — and the model never saw the client's identity (Solomon boundary round-trip).
4. **The audit view** shows the full chain: known-since, dependency, the change event, the flag, the verification prompt.

Side-by-side with the warehouse baseline failing step 3 is the demo GIF and the core of the writeup.

---

## 8. Why this is credible to Anthropic / OpenAI (FDE lens)

- **Composition under constraint is the FDE job.** Solomon is literally "take two hard-won primitives (a safety gateway, a memory discipline) and compose them into a domain solution the customer can actually deploy." That is the role.
- **Domain judgment.** Choosing to reject decay, to model dependencies rather than similarity, and to make the system *refuse to assert* rather than fake a truth verdict — these are judgment calls a reviewer can probe and that hold up.
- **It composes under constraint.** Boundary, currency, retrieval, routing, and audit work together inside one deployable system.
- **Honest scope.** Solomon doesn't claim to decide the law. It surfaces currency and defers judgment — the same posture the courts and bar opinions demand of AI in legal work.

---

## 9. Explicit relationship to Shibahama (why it's not a reskin)

Shibahama's thesis is **decay**: significance fades with neglect; the engine forgets adaptively. Solomon's thesis is the **inverse**: in law nothing should fade, because an old position is not a less-important position — it is either still-good or superseded, which is a currency question, not a significance one. Solomon therefore *cannot* be Shibahama with legal config; it needs a different core (dependency-driven currency, not usage-driven decay). Building both, and being able to articulate *why they needed opposite mechanisms*, is the strongest possible demonstration that each problem was understood rather than pattern-matched.

Shared concepts (bi-temporality, credence, verification, never-delete) are implemented directly in Solomon because the constraints differ from generic memory systems.

---

## 10. Risks & honest limitations

- **Dependency capture is manual at first.** Knowing that a memo depends on R §12 requires extraction; early versions lean on human tagging + LLM-assisted suggestion. Honest about it; it's the curation cost the market already pays a person for.
- **Solomon flags, it does not adjudicate.** It cannot decide whether an amended regulation actually breaks a position — only that the dependency moved and re-verification is due. Overclaiming here would be the exact hubris the bar warns against.
- **Sanitisation fidelity is bounded by the boundary.** A tokenisation failure can leak across the boundary; Solomon mitigates this with strict profiles and fixture coverage.
- **External-change ingestion is a data problem.** Knowing R §12 changed requires a feed; v1 supports manual + simple feeds, not comprehensive regulatory monitoring (that's a Shepard's-scale undertaking and explicitly out of scope).
- **No new model training.** Solomon is orchestration + reasoning over existing models; it deliberately avoids the "train a legal model" trap.

---

## 11. Deliverable package

Single signature repo (`solomon/`), deep README that *is* the writeup: the architecture, the stale-house-view demo GIF, the warehouse-baseline comparison, and an honest-limitations section. Docs live in-repo. No separate paper.
