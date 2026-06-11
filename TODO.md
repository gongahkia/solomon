# Solomon — Implementation TODO

A good-law engine for the firm's own knowledge, behind a zero-retention boundary.

**Assumed layout:** Solomon lives at `./solomon/`, with Kaypoh as an untouched sibling at `../kaypoh/`. Solomon imports Kaypoh's Python client (`../kaypoh/src/kaypoh/client.py` → `KaypohClient`) and calls its running service; it never modifies Kaypoh source. Where a task says "reuse Kaypoh," it means call the API or mirror the pattern, not fork the code.

Priority scale: **P0** = must exist to function · **P1** = core thesis / launch-credible · **P2** = strong differentiator · **P3** = polish / stretch.
Phases are ordered but P-tags cut across; clear P0s in a phase before P2s in the same phase.

Legend for Kaypoh touchpoints: 🔌 = integrates with Kaypoh · 🆕 = net-new to Solomon · ♻️ = mirror a Kaypoh pattern in Solomon's own code.

---

## Phase 0 — Foundations, repo, and the triad story

### Repo & tooling
- [x] (P0) Initialise `solomon/` as a sibling to `../kaypoh/`; confirm relative-path assumption in README
- [x] (P0) Python 3.10+ project managed by `uv` (♻️ match Kaypoh's toolchain for a coherent triad)
- [x] (P0) Layout: `src/solomon/{currency,graph,store,credence,boundary,orchestrator,audit,api,cli}/`, `tests/`, `examples/`, `docs/`, `benchmarks/`
- [x] (P0) FastAPI + Pydantic v2 app skeleton (♻️ mirror Kaypoh's `backend/` shape so the two read as a family)
- [x] (P0) `pyproject.toml` with a path dependency or documented import of `../kaypoh` client
- [x] (P0) `ruff` + `mypy` + `pytest` configured; deny-warnings in CI
- [x] (P0) GitHub Actions: lint, type-check, test, and a Kaypoh-integration smoke job (spins up kaypoh-local)
- [x] (P0) Licence + SPDX headers; `CONTRIBUTING.md`; minimal README stub (full README in Phase 16)
- [x] (P1) `CHANGELOG.md` (keep-a-changelog); semver
- [x] (P1) Issue/PR templates; `CODEOWNERS`
- [x] (P2) Pre-commit hooks (ruff, mypy, secret scan)
- [x] (P2) Devcontainer / Nix flake that brings up both Solomon and a kaypoh-local instance

### ADRs (write in `docs/adr/`) — these encode the judgment a reviewer will probe
- [x] (P0) ADR: **why reject decay** (Shibahama's mechanism) in favour of dependency-driven currency
- [x] (P0) ADR: bi-temporal model (valid-time vs ingestion-time) and the supersede-not-delete invariant
- [x] (P0) ADR: **flag, don't adjudicate** — Solomon never asserts a position is legally broken, only that a dependency moved and re-verification is due
- [x] (P0) ADR: Kaypoh as boundary — reuse vs reimplement decision table (point to PRD §4)
- [ ] (P1) ADR: credence taxonomy + the "model-inferred never outranks firm-authoritative" rule
- [ ] (P1) ADR: dual-endpoint routing (remote ZDR vs local model) and the sensitivity classification that drives it
- [ ] (P1) ADR: audit-journal design (♻️ mirror Kaypoh's append-only journal + verification)

---

## Phase 1 — Bi-temporal knowledge store (🆕 core substrate)

### Data model
- [x] (P0) Define `KnowledgeItem`: id, kind (position/clause/house-view/advice/note), content, embedding ref, provenance, `valid_from`, `valid_to` (nullable=open), `ingested_at`, credence_tier, currency_state, `last_verified_at`, `verified_by`
- [x] (P0) Define `currency_state` enum: Live / StalePendingReverification / Superseded / Retired
- [x] (P0) Define `Provenance`: source kind (partner/associate/matter-doc/external-feed/model), source ref, author, matter id
- [x] (P0) Define `CredenceTier` enum: FirmAuthoritative / Verified / ModelInferred / Unverified
- [x] (P0) UUID v7 ids (time-orderable); schema version field on every persisted item
- [x] (P1) Define `Matter` and `Client` scoping entities (knowledge is scoped; cross-matter queries are explicit)
- [x] (P1) Define `ExternalAuthority`: statute/regulation/case ref, jurisdiction, current version, version history

### Storage engine
- [x] (P0) Choose store (SQLite default for local SKU; Postgres option for server) — write ADR
- [x] (P0) Append-only event log as source of truth (♻️ Kaypoh journal philosophy: nothing destructive)
- [x] (P0) Materialised current-state table derived from the log
- [x] (P0) `write_item()`, `get_item()`, `get_many()`
- [x] (P0) **Supersede operation**: close `valid_to`, set Superseded, link successor — never DELETE
- [x] (P0) Invariant test: no code path deletes a knowledge item
- [x] (P1) `as_of(timestamp)` query: reconstruct the knowledge state at any past date (bi-temporal core capability)
- [x] (P1) Crash-safe writes + recovery on startup
- [x] (P1) Snapshot/restore of full firm-knowledge state to a portable file
- [ ] (P2) Encryption-at-rest (♻️ mirror Kaypoh `mapping-store-hardening` patterns)
- [ ] (P2) Pluggable backend so SQLite↔Postgres is a config switch

### Vector / retrieval index
- [x] (P0) Define embedding strategy and an index backend (local: sqlite-vss/lancedb; server: pgvector/qdrant)
- [x] (P0) Keep item↔vector consistent through supersession (superseded items leave default retrieval but stay queryable)
- [x] (P1) Store embedding model + version so re-embeds are detectable
- [x] (P2) Batch ingestion path

---

## Phase 2 — Dependency graph (🆕 the technically interesting structure)

- [x] (P0) Define edge types: `internal_depends_on_external` (item → ExternalAuthority §), `internal_depends_on_internal` (item → item), `supersedes` (item → item)
- [x] (P0) Graph storage co-located with the knowledge store; edges are bi-temporal too (a dependency was valid for a period)
- [x] (P0) `add_dependency()`, `get_dependencies(item)`, `get_dependents(authority_or_item)`
- [x] (P1) **Propagation engine**: when an ExternalAuthority version changes or an item is superseded, walk dependents and set StalePendingReverification (transitively, with cycle protection)
- [x] (P1) Record *why* an item is stale (which dependency moved, when) — feeds the flag explanation and the audit chain
- [x] (P1) `impact_query(authority)`: "the regulation changed — everything that now needs re-checking" (the query no warehouse KM can answer)
- [x] (P2) Confidence on dependency edges (human-asserted vs LLM-suggested) — affects how aggressively staleness propagates
- [x] (P2) Graph centrality as an input to surfacing order (well-depended-on positions rank earlier when relevant)
- [x] (P2) Subgraph extraction per matter/client for scoped review
- [ ] (P3) Visualise the dependency graph (internal knowledge hanging off external authorities)

### Dependency capture (honest about the manual cost)
- [ ] (P1) Manual dependency tagging API + CLI (the baseline; the market already pays a curator to do this)
- [ ] (P2) LLM-assisted dependency suggestion: extract candidate authority references from an item (routed through Kaypoh first — see Phase 4)
- [ ] (P2) Human-in-the-loop confirm/reject for suggested dependencies (suggested = lower edge confidence until confirmed)
- [ ] (P3) Defined-term / citation extraction (could 🔌 reuse Kaypoh's `defined_terms` / `citations` patterns as a reference)

---

## Phase 3 — Currency engine (🆕 the good-law-for-firm-knowledge core, P1 #1)

- [x] (P0) Define currency as a function of (validity of all dependencies) × (staleness of verification) × (item own valid_to)
- [x] (P0) `evaluate_currency(item)` → currency_state + explanation (what's live/stale/superseded and why)
- [x] (P0) Default query path returns Live items; Stale/Superseded surface only with explicit flags or in review mode
- [x] (P1) `verification_due(item)` policy: configurable max age since `last_verified_at`, shorter for high-stakes kinds
- [x] (P1) `record_verification(item, by, outcome)`: refresh `last_verified_at`; outcome can re-affirm, supersede, or retire
- [ ] (P1) Supersession reasoning: when a newer item contradicts an older one on the same (topic, jurisdiction), propose supersession (human confirms — flag, don't adjudicate)
- [x] (P1) External-change ingestion: `register_authority_change(authority, new_version, date)` → triggers Phase-2 propagation
- [ ] (P2) Simple external feeds (manual entry + a couple of structured regulatory-update sources); NOT comprehensive monitoring (out of scope, that's Shepard's-scale)
- [ ] (P2) Currency report for a matter/client: everything we've relied on and its current state
- [ ] (P3) Predictive "likely to go stale soon" heuristic (authority with pending amendments)

---

## Phase 4 — Boundary integration with Kaypoh (🔌 P1 #4 — wire, don't build)

- [x] (P0) Import `KaypohClient` from `../kaypoh`; config for kaypoh-local vs kaypoh-server base URL
- [x] (P0) **Ingestion gate**: every new KnowledgeItem passes Kaypoh `/review` before storage; capture findings (MNPI markers, severity) onto the item's provenance
- [x] (P0) Refuse or quarantine items Kaypoh flags as unsafe-to-store per policy (configurable)
- [x] (P0) **Outbound sanitisation**: any context assembled for a model call goes through Kaypoh `/pseudonymize`; keep the returned mapping in volatile memory only
- [x] (P0) **Inbound demasking**: model response → Kaypoh `/reidentify` using the volatile mapping; flush mapping after
- [x] (P1) Use `KAYPOH_LLM_INPUT_MODE=structured_tokens` semantics — never send raw_text by default; gate raw_text behind explicit per-matter opt-in
- [x] (P1) Handle Kaypoh degraded-mode / unavailability: fail CLOSED (no egress if the boundary is down)
- [x] (P1) Pass source+destination jurisdiction to Kaypoh so the strictest rule resolves correctly
- [x] (P2) Reconcile demasking correctness when the model rephrases/reasons over tokens (test that placeholders survive paraphrase; flag when a token is dropped/mangled)
- [x] (P2) Document-scrub path for ingested files (🔌 Kaypoh `/documents/scrub`) before extraction
- [ ] (P3) Reuse Kaypoh's Word/Outlook add-in surfaces as optional Solomon front-ends (🔌 `../kaypoh/packaging/word_addin`)

---

## Phase 5 — Dual model endpoint & routing (🆕)

- [x] (P0) Define `ModelEndpoint` abstraction: remote-ZDR provider and local in-perimeter model behind one interface
- [x] (P0) Implement a remote ZDR-eligible provider client (assume ZDR terms; send only sanitised context)
- [x] (P0) Implement a local model client (e.g. vLLM/Ollama-compatible, in-perimeter)
- [x] (P1) **Sensitivity classifier / router**: matter sensitivity decides remote-vs-local; strict matters never egress even sanitised (local-only)
- [x] (P1) Make the routing decision auditable (log which endpoint, why, what crossed — metadata only)
- [x] (P1) Graceful degradation: if remote unavailable and matter allows, fall back to local with a quality caveat
- [x] (P2) Local-only zero-egress mode for the strictest tier (no sanitised egress at all)
- [x] (P2) Cost/latency metadata per call (♻️ Kaypoh-style metrics, content-free)

---

## Phase 6 — Credence ledger & verification step (🆕 P1 #2)

- [x] (P0) Credence tier assigned on ingest by source kind (partner-signed → FirmAuthoritative; model output → ModelInferred; etc.)
- [x] (P0) Per-item `verified_state` + `last_verified_at` + `verified_by`
- [x] (P1) **Retrieval guardrail**: ModelInferred/Unverified items can never outrank FirmAuthoritative on equal relevance
- [x] (P1) **Verification step before load-bearing output**: surface source pointer + currency state; refuse to present a stale/low-credence item as settled
- [x] (P1) Quarantine model-generated facts at low credence; promotion needs corroboration or human confirm (♻️ skeptical-by-default, OWASP ASI06 posture)
- [x] (P1) Separate "facts/positions" from "instructions" so retrieved knowledge can't inject directives into the prompt
- [x] (P2) Credence-change audit (who raised/lowered a tier and why)
- [x] (P2) Configurable per-firm credence policy

---

## Phase 7 — Retrieval orchestrator (🆕)

- [x] (P0) `recall(query, matter_context)` → ranked KnowledgeItems with currency_state + provenance + dependencies (never bare text)
- [x] (P0) Stage 1: semantic similarity retrieval
- [x] (P0) Stage 2: currency filter (Live by default; annotate, don't silently drop, when surfacing stale in review mode)
- [x] (P1) Stage 3: dependency-graph expansion (pull in what an item relies on, and flag if any dependency moved)
- [x] (P1) Stage 4: credence weighting
- [x] (P1) Attach to every result: currency_state, what it depends on, what superseded it (if any), last_verified
- [x] (P1) `timeline(query, as_of)`: what did the firm believe on date X (bi-temporal query surfaced to users)
- [x] (P2) Tunable ranking weights (similarity ⊕ currency ⊕ credence ⊕ centrality)
- [x] (P2) De-duplication of near-identical positions across matters
- [ ] (P3) Query budget controls (max context tokens assembled before sanitisation)

---

## Phase 8 — Audit & privilege evidence chain (🆕 P1 #3, ♻️ Kaypoh journal)

- [x] (P0) Append-only audit journal (♻️ mirror `../kaypoh` journal + `verify_journal` pattern)
- [x] (P0) Log per query: what was known, currency states surfaced, what verification ran, which endpoint, what crossed the boundary (metadata only — never content)
- [x] (P1) Log the full dependency/staleness chain for any flagged item (the "why was this stale" record)
- [x] (P1) Audit-pack export + verify (♻️ Kaypoh `export_audit_pack` / `verify_audit_pack` patterns) — the defensibility artifact
- [x] (P1) Tamper-evidence on the journal (hash chaining)
- [x] (P2) "What did we know and when" report for a given matter/client (privilege defence narrative)
- [x] (P2) Right-to-erasure handling for stored knowledge where lawful (♻️ Kaypoh `erase_subject` philosophy), reconciled with the never-delete-for-audit tension (document the resolution)
- [ ] (P3) Signed verification attestations (who verified, cryptographically)

---

## Phase 9 — Public API & CLI (🆕)

- [x] (P0) Finalise API verbs: `ingest`, `recall`, `evaluate_currency`, `record_verification`, `register_authority_change`, `impact_query`, `why(item)`, `timeline`
- [x] (P0) Make `why(item)` first-class: full currency + dependency + credence + verification + provenance trace
- [x] (P0) FastAPI surface (♻️ Kaypoh-style schemas, auth, health/ready/diagnostics endpoints)
- [x] (P1) `solomon` CLI: ingest a doc, ask, show currency, register a regulatory change, run an impact query, export audit pack
- [x] (P1) Stable error types; fail-closed behaviour surfaced clearly
- [x] (P1) Config object with sane defaults (verification-due ages, routing thresholds, credence policy)
- [x] (P2) Python client (♻️ mirror Kaypoh's `client.py` ergonomics: sync + async over httpx)
- [x] (P2) Pretty terminal `why` output (text version of the currency trace)

---

## Phase 10 — Local vs server SKU (♻️ mirror Kaypoh's SKU model)

- [x] (P1) `solomon-local`: offline-default, SQLite, local model, talks to kaypoh-local; no outbound HTTP except the configured local model
- [x] (P1) `solomon-server`: Postgres option, remote-ZDR endpoint allowed, talks to kaypoh-server; env-gated egress
- [x] (P1) Env-gating for any egress (♻️ Kaypoh's explicit-opt-in discipline: nothing leaves without a flag)
- [x] (P2) PyInstaller desktop packaging for solomon-local (♻️ Kaypoh `packaging/` approach)
- [x] (P2) Docker compose for server (♻️ mirror Kaypoh compose files)
- [ ] (P3) Multi-tenant namespace isolation on server

---

## Phase 11 — Headline demo: the stale house-view (🆕 P1)

- [ ] (P0) Build a scripted, reproducible scenario fixture: 2023 house-view memo depending on Regulation R §12, relied on in a Client A matter
- [ ] (P0) Script the 2025 regulatory change + propagation to StalePendingReverification
- [ ] (P1) 2026 associate query → Solomon flags the memo (depends on R §12 changed 2025; not re-verified; last relied on in Client A; recommend re-check)
- [ ] (P1) Verify the model never saw the client identity (assert Kaypoh round-trip masked/demasked correctly)
- [ ] (P1) **Warehouse-KM baseline**: a similarity-only retriever that returns the 2023 memo confidently with no staleness signal — the side-by-side
- [ ] (P1) Audit view rendering the full chain (known-since → dependency → change event → flag → verification prompt)
- [ ] (P2) Record the run for the README GIF
- [ ] (P2) Package as a runnable `examples/stale-house-view/` (clone, bring up kaypoh-local, run)
- [ ] (P3) A second scenario (e.g. internal supersession: a 2024 position quietly overriding a 2022 one) to show supersession reasoning

---

## Phase 12 — Evaluation (🆕, leans on the demo + a small currency benchmark)

- [ ] (P1) Synthetic firm-knowledge corpus generator (positions/memos/advice with dependencies + injected changes over time)
- [ ] (P1) Metric: **stale-surface rate** — how often each system surfaces a stale internal item as current
- [ ] (P1) Metric: **time-to-flag** after a dependency changes (propagation correctness)
- [ ] (P1) Metric: **impact-query recall** — given a change, did we flag everything that depended on it
- [ ] (P1) Baselines: a similarity-only warehouse retriever; (optionally) a Shibahama-style decay retriever to show decay is *wrong* here (old≠stale)
- [ ] (P2) Boundary-fidelity eval: end-to-end, did anything sensitive cross? (lean on Kaypoh's recall numbers; test the integration, not re-test Kaypoh)
- [ ] (P2) Ablations: dependency graph on/off, credence guardrail on/off, currency filter on/off
- [ ] (P2) Results table for the README (stale-surface rate: Solomon vs warehouse vs decay)
- [ ] (P3) Release the corpus generator so the eval is reproducible

---

## Phase 13 — Testing & correctness (P0/P1, cross-cutting)

- [ ] (P0) Unit tests: data model, bi-temporal invariants, supersede-not-delete, currency_state transitions
- [ ] (P0) Property test: no path deletes a knowledge item
- [ ] (P0) Property test: superseded/stale items never appear in default (Live) recall without a flag
- [ ] (P1) Property test: ModelInferred never outranks FirmAuthoritative at equal relevance
- [ ] (P1) Propagation test: authority change flags exactly the transitive dependents, no more, no fewer; cycles terminate
- [ ] (P1) `as_of` correctness: historical reconstruction matches the event log
- [ ] (P1) **Boundary test: fail-closed** — if Kaypoh is unreachable, no context egresses
- [ ] (P1) Round-trip test: pseudonymize→model→reidentify preserves meaning and leaks nothing (incl. paraphrase-survival of tokens)
- [ ] (P1) Routing test: strict matters never hit the remote endpoint
- [ ] (P2) Fuzz ingestion with adversarial/malformed items
- [ ] (P2) Poisoning red-team: plant a false ModelInferred "position", assert it can't outrank or be asserted as settled
- [ ] (P2) Soak test: thousands of items + many authority changes; propagation stays correct and bounded
- [ ] (P2) Kaypoh-integration contract tests (pin the client behaviour Solomon relies on)

---

## Phase 14 — Performance & hardening (P2)

- [ ] (P1) Recall + currency-evaluation latency budget (p50/p95)
- [ ] (P1) Ensure propagation is incremental (a change touches only dependents, no full-graph rescan)
- [ ] (P2) Index the dependency graph for fast `impact_query`
- [ ] (P2) Concurrency: safe multi-reader/single-writer (or MVCC) on the store
- [ ] (P2) Memory/footprint budget for solomon-local
- [ ] (P3) Caching of currency evaluations with correct invalidation on dependency change

---

## Phase 15 — Security & governance (♻️ mirror Kaypoh series)

- [ ] (P1) Threat model doc (`docs/threat-model.md`) — esp. the boundary, the store, and poisoning (ASI06)
- [ ] (P1) Fail-closed egress everywhere; document the trust boundary precisely
- [ ] (P1) Treat the knowledge store as an untrusted input surface on read (sanitise stored instructions)
- [ ] (P2) Auth/tenancy (♻️ Kaypoh `auth.py` patterns) for server SKU
- [ ] (P2) Mapping/volatile-memory hygiene: assert no sanitisation mapping is ever persisted by Solomon
- [ ] (P2) `docs/known-limitations.md` and `docs/assumption.md` (♻️ Kaypoh's design-honesty docs)
- [ ] (P3) Independent boundary audit checklist

---

## Phase 16 — Docs inside the repo (P1, minimal, repo-internal)

- [ ] (P0) Deep `README.md` — the writeup: the triad framing (Kaypoh/Shibahama/Solomon table), the wedge, architecture diagram, stale-house-view demo GIF, warehouse baseline comparison, honest limitations (README IS the paper)
- [ ] (P1) `docs/architecture.md`: components, data model, request lifecycle, the boundary
- [ ] (P1) `docs/concepts.md`: currency vs significance, bi-temporality, dependency graph, credence, verification — in plain language
- [ ] (P1) `docs/kaypoh-integration.md`: exactly what Solomon reuses, what it builds, how to run both together
- [ ] (P1) Generated API reference (FastAPI/OpenAPI export, ♻️ Kaypoh's `export_openapi_examples` approach)
- [ ] (P1) `examples/` runnable per scenario
- [ ] (P2) `docs/benchmarks.md`: methodology + reproduce instructions
- [ ] (P2) ADR index kept current
- [ ] (P3) `docs/why-solomon.md`: the triad story + why decay was rejected (the judgment narrative for a reviewer)

---

## Phase 17 — Launch (P1/P2)

- [ ] (P0) Tag `v0.1.0`; publish (pip; desktop bundle for local SKU)
- [ ] (P1) Record the stale-house-view demo GIF (Solomon flag vs warehouse miss)
- [ ] (P1) Write the launch post leading with the wedge: "every firm checks if a *case* is still good law; nobody checks if *their own* knowledge is — Solomon does, behind a zero-retention boundary"
- [ ] (P1) FAQ for predictable objections (isn't this KM? how is it not Shibahama? does it decide the law? what if Kaypoh mis-detects?)
- [ ] (P1) The triad writeup: one diagram showing Kaypoh + Shibahama + Solomon and what each proves (the FDE-application centrepiece)
- [ ] (P2) Early-user outreach; collect first issues
- [ ] (P3) Submit the currency-eval writeup somewhere citable
