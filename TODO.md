# Solomon — Implementation TODO, reconciled to current ground truth

This file is the current-state TODO, not an aspirational completion ledger. A checked item means the current
worktree has code and tests or runnable evidence for it. An unchecked item is partial, shallow, unverified, or
not built yet. There is no Phase 18 in this plan.

Kaypoh boundary status: Solomon is now self-contained. The local boundary engine is vendored under
`src/solomon/boundary/engine/` from Kaypoh commit `7415069e57d69398e2c44ef6ababafb0c04a988b`; no `../kaypoh`
checkout is required at runtime.

---

## Phase 0 — Foundations, repo, and the triad story

- [x] Python 3.10+ `uv` project with `src/solomon/{currency,graph,store,credence,boundary,orchestrator,audit,api,cli}/`, tests, examples, docs, and benchmarks.
- [x] FastAPI + Pydantic v2 service skeleton, CLI entrypoint, ruff/mypy/pytest config, GitHub Actions, issue/PR templates, CODEOWNERS, license, changelog, devcontainer/Nix files.
- [x] ADRs exist for decay rejection, bi-temporal supersession, flag-don't-adjudicate, boundary, credence, routing, and audit.
- [x] Boundary assumption updated from sibling Kaypoh import to vendored in-process boundary.

## Phase 1 — Bi-temporal knowledge store

- [x] `KnowledgeItem`, provenance, credence, currency state, matter/client, and external-authority models exist.
- [x] SQLite append-only event log, materialized current table, `write_item()`, `get_item()`, `get_many()`, supersede-not-delete, `as_of()`, snapshot/restore, and no-delete tests exist.
- [x] Encryption helper for portable artifacts exists.
- [ ] Postgres backend is not implemented; `create_knowledge_store()` rejects Postgres with `UnsupportedStoreBackend`.
- [ ] Retrieval index is lexical token-set, not sqlite-vss/LanceDB/pgvector/Qdrant.
- [ ] Embedding lifecycle is minimal: model/version is stored as an `embedding_ref`, but there is no real re-embed pipeline.

## Phase 2 — Dependency graph

- [x] Three edge types exist: external dependency, internal dependency, and supersedes.
- [x] Graph storage is co-located in SQLite and supports valid-time reads, `add_dependency()`, `get_dependencies()`, and `get_dependents()`.
- [x] Propagation is real: external changes flag transitive dependents and cycle protection is tested.
- [x] `impact_query()` now returns the transitive dependent set without mutating store state.
- [x] Manual dependency tagging, confidence levels, centrality, scoped subgraphs, and basic Mermaid/DOT visualization exist.
- [ ] LLM-assisted dependency capture is deterministic regex extraction over boundary-sanitized text, not an actual LLM workflow.
- [ ] Defined-term/citation extraction is conservative regex extraction, not a full legal parser.

## Phase 3 — Currency engine

- [x] `evaluate_currency()` computes from `valid_to`, stored stale/superseded/retired state, staleness reasons, and verification age.
- [x] Default recall now filters on computed currency and avoids returning items whose displayed currency contradicts the filter.
- [x] `record_verification()` supports reaffirm, retire, and supersede; `register_authority_change()` triggers propagation.
- [x] JSON authority-change feed and matter/client currency report exist.
- [ ] External monitoring is manual/JSON only, not comprehensive regulatory monitoring.
- [ ] Predictive staleness is a simple pending-amendment heuristic, not a legal-change forecasting system.

## Phase 4 — Boundary integration

- [x] Kaypoh-derived review, pseudonymize/anonymize/reidentify, volatile mapping, jurisdiction pack, document scrub, and client surfaces are vendored under Solomon's namespace.
- [x] Vendored `NOTICE` records the Kaypoh source commit and README/docs state the provenance.
- [x] `SolomonService.ingest()` calls boundary review before store/index writes and captures findings on provenance.
- [x] `SolomonService.complete_model_request()` sanitizes before router/model egress, reidentifies inbound text, and flushes mappings.
- [x] Service-level fail-closed tests prove vendored boundary failure blocks ingestion and model egress before endpoint calls.
- [ ] Vendored boundary is intentionally compact and deterministic; it is not full Kaypoh feature parity.

## Phase 5 — Dual model endpoint and routing

- [x] Remote-ZDR and local endpoint abstractions exist with model-call metadata.
- [x] Sensitivity router sends strict and zero-egress matters local-only, with tests proving the remote endpoint is not called.
- [x] Remote failure can fall back to local when policy allows.
- [x] Public `/answer` API endpoint runs recall -> boundary sanitization/reidentification -> router -> model answer and returns recall/model audit evidence.
- [ ] Provider clients are minimal HTTP wrappers, not production provider integrations.

## Phase 6 — Credence ledger and verification

- [x] Credence tier is assigned from source kind; model output is low credence and needs review.
- [x] `ModelInferred` cannot outrank `FirmAuthoritative` at equal relevance, with unit and property tests.
- [x] Load-bearing decision helper refuses stale or low-credence items; instruction-role content is excluded from prompt context.
- [x] Credence changes are audited in memory.
- [ ] Load-bearing refusal is not enforced globally across every API path.
- [x] Credence audit entries are persisted to the main hash-chained audit journal by default on service ingest without storing item content.

## Phase 7 — Retrieval orchestrator

- [x] `recall()` returns ranked `KnowledgeItem` results with currency, provenance, dependencies, supersession, last verification, stale reasons, and token estimates.
- [x] `timeline(query, as_of)` reconstructs historical state from the event log.
- [x] Review mode surfaces stale/superseded items; default mode filters computed non-Live items.
- [x] Scope filters, basic dedupe, centrality weighting, credence weighting, and context budget controls exist.
- [ ] Retrieval is lexical token-set search, not semantic vector search.
- [ ] Ranking weights are simple local scoring, not empirically tuned.

## Phase 8 — Audit and privilege evidence chain

- [x] Append-only hash-chained audit journal, tamper verification, audit-pack export/verify, metadata-only query logging, erasure tombstones, and HMAC verification attestations exist.
- [x] Stale-house-view demo now renders the dependency-change -> stale-flag -> verification-prompt chain.
- [x] `/answer` records a single metadata-only `answer_workflow` audit transaction tying recall context ids, boundary metadata, and model-call audit together.
- [x] Signed attestations support Ed25519 public-key signing and verification with tamper tests, alongside the existing local HMAC mode.

## Phase 9 — Public API and CLI

- [x] API exposes ingest, recall, currency, verification, authority change, dependency add, impact, graph, references, staleness prediction, why, and timeline.
- [x] Python sync/async client exists for ingest/recall/why.
- [x] Server-mode middleware enforces API key and tenant isolation.
- [x] CLI direct test coverage exists for version/diagnostics plus ingest -> recall -> why on an isolated local store.
- [x] OpenAPI export has been regenerated after boundary/ingest schema changes.

## Phase 10 — Local vs server SKU

- [x] Local SKU defaults to offline/zero-egress with SQLite and in-process boundary.
- [x] Server settings require explicit remote model URL before remote egress.
- [x] Docker compose and PyInstaller spec files exist.
- [ ] Postgres server backend is not implemented.
- [ ] PyInstaller and Docker artifacts are not built or verified in this worktree.
- [ ] Server multi-tenancy is basic filesystem namespace isolation, not a full tenant-management system.

## Phase 11 — Headline demo: stale house-view

- [x] `examples/stale-house-view/run.py` creates the 2023 memo, 2025 authority change, 2026 query, Solomon flag, warehouse-baseline miss, boundary masking proof, and audit chain.
- [x] Demo uses the real vendored boundary, not a fake client.
- [x] Internal supersession example exists.
- [x] README GIF has been re-rendered with `scripts/render_stale_house_view_gif.py` and matches the committed asset.

## Phase 12 — Evaluation

- [x] Synthetic corpus generator exists and exports reproducible items, dependencies, changed authority, and oracle stale ids.
- [x] Evaluation harness now actually writes the corpus to store/graph/index, runs propagation, recall, warehouse baseline, decay baseline, and timing.
- [x] Metrics include stale-surface rate, time-to-flag, and impact-query recall.
- [ ] Evaluation remains synthetic and curated; it is not a jurisdictional coverage benchmark or external-law-monitoring benchmark.
- [ ] Boundary-fidelity evaluation is a small forbidden-term scan, not a full Kaypoh recall evaluation.

## Phase 13 — Testing and correctness

- [x] Unit/property tests cover store invariants, supersede-not-delete, `as_of()`, recall filtering, credence ranking, propagation cycles, boundary fail-closed, routing, audit, demo, and evaluation helpers.
- [x] Service-level boundary tests now cover ingestion and model egress fail-closed behavior with the vendored engine forced to fail.
- [x] Soak test covers 300 direct dependents.
- [x] Fuzz/property coverage now includes non-empty service ingest round trips with metadata-only audit checks and generated-text retrieval invariants in addition to empty-content rejection.
- [x] Desktop packaging tests validate the PyInstaller local binary spec, CLI entrypoint, packaging dependency, and documented artifact names.

## Phase 14 — Performance and hardening

- [x] SQLite WAL and busy timeout are configured and tested.
- [x] Latency/memory budget helper functions exist.
- [x] Graph target indexes support fast direct dependent lookup.
- [x] CI enforces a real local recall p50/p95 benchmark gate via `benchmarks/performance_budget.py` over a temporary indexed corpus.
- [x] SQLite concurrency is characterized by a multi-connection WAL write test and documented local write envelope.
- [x] Currency cache correctness is directly tested for item-state fingerprints, metadata staleness reasons, as-of-day changes, authority-change invalidation, and verification invalidation.

## Phase 15 — Security and governance

- [x] Threat model, trust-boundary docs, known limitations, assumptions, erasure docs, and boundary audit checklist exist.
- [x] Fail-closed boundary behavior is enforced in service-level tests.
- [x] Volatile mapping hygiene is tested.
- [ ] Auth/tenancy is basic API-key/header middleware, not a full auth system.
- [ ] Stored-knowledge sanitization is limited to instruction-role separation and boundary-on-ingest, not deep content hardening.

## Phase 16 — Repo docs

- [x] README, architecture, concepts, Kaypoh integration, trust boundary, benchmark/evaluation, and ADR docs exist.
- [x] Docs now describe the vendored boundary design and pinned source commit.
- [x] Generated OpenAPI has been refreshed after schema/API changes.
- [x] Launch/readme media is current: `docs/assets/stale-house-view-demo.gif` was re-rendered from the checked-in script.

## Phase 17 — Launch

- [x] Launch post, FAQ, outreach docs, packaging README, and citation metadata exist.
- [ ] No git tag is present in this worktree.
- [ ] No built pip or desktop artifacts are present in `dist/`.
- [ ] Early-user outreach and eval submission are docs, not externally verifiable release activity.
