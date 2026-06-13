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
- [x] Postgres backend exists for the knowledge event store/current projection, dependency graph, and retrieval index; `create_knowledge_store()` and `create_storage_bundle()` accept Postgres URLs with optional `solomon[server]` driver support.
- [x] Retrieval index is SQLite-backed vector search with stable hashed legal-domain token embeddings, vector persistence, cosine scoring, and schema migration.
- [x] Embedding lifecycle includes stale/missing `embedding_ref` detection and a `reembed_stale_items()` pipeline that reindexes store items after strategy version changes.

## Phase 2 — Dependency graph

- [x] Three edge types exist: external dependency, internal dependency, and supersedes.
- [x] Graph storage is co-located in SQLite and supports valid-time reads, `add_dependency()`, `get_dependencies()`, and `get_dependents()`.
- [x] Propagation is real: external changes flag transitive dependents and cycle protection is tested.
- [x] `impact_query()` now returns the transitive dependent set without mutating store state.
- [x] Manual dependency tagging, confidence levels, centrality, scoped subgraphs, and basic Mermaid/DOT visualization exist.
- [x] LLM-assisted dependency capture exists as an optional boundary-sanitized model workflow with strict JSON validation and human-confirmation semantics.
- [x] Defined-term/citation extraction uses `eyecite` for legal citations plus Solomon's deterministic grammar for firm-style authorities, non-US case strings, and defined terms, with parser/span metadata in API output.

## Phase 3 — Currency engine

- [x] `evaluate_currency()` computes from `valid_to`, stored stale/superseded/retired state, staleness reasons, and verification age.
- [x] Default recall now filters on computed currency and avoids returning items whose displayed currency contradicts the filter.
- [x] `record_verification()` supports reaffirm, retire, and supersede; `register_authority_change()` triggers propagation.
- [x] JSON authority-change feed and matter/client currency report exist.
- [x] External monitoring includes an HTTP authority-change feed poller with ETag/Last-Modified conditional requests and 304 handling, in addition to local JSON/CSV feeds.
- [x] Predictive staleness now uses a feature-scored forecast over pending amendments, status, dependency confidence, graph centrality, and authority change history.

## Phase 4 — Boundary integration

- [x] Kaypoh-derived review, pseudonymize/anonymize/reidentify, volatile mapping, jurisdiction pack, document scrub, and client surfaces are vendored under Solomon's namespace.
- [x] Vendored `NOTICE` records the Kaypoh source commit and README/docs state the provenance.
- [x] `SolomonService.ingest()` calls boundary review before store/index writes and captures findings on provenance.
- [x] `SolomonService.complete_model_request()` sanitizes before router/model egress, reidentifies inbound text, and flushes mappings.
- [x] Service-level fail-closed tests prove vendored boundary failure blocks ingestion and model egress before endpoint calls.
- [x] Vendored boundary now covers the Kaypoh product surfaces Solomon depends on: review, pseudonymize, irreversible anonymize, opaque redact, reidentify, document scrub, capabilities, 18 jurisdiction packs, richer deterministic PII/MNPI detectors, and parity tests.

## Phase 5 — Dual model endpoint and routing

- [x] Remote-ZDR and local endpoint abstractions exist with model-call metadata.
- [x] Sensitivity router sends strict and zero-egress matters local-only, with tests proving the remote endpoint is not called.
- [x] Remote failure can fall back to local when policy allows.
- [x] Public `/answer` API endpoint runs recall -> boundary sanitization/reidentification -> router -> model answer and returns recall/model audit evidence.
- [x] Provider clients include an OpenAI Responses integration with provider-specific payloads, output parsing, auth, retry/backoff, and tests, plus generic retrying remote ZDR support.

## Phase 6 — Credence ledger and verification

- [x] Credence tier is assigned from source kind; model output is low credence and needs review.
- [x] `ModelInferred` cannot outrank `FirmAuthoritative` at equal relevance, with unit and property tests.
- [x] Load-bearing decision helper refuses stale or low-credence items; instruction-role content is excluded from prompt context.
- [x] Credence changes are audited in memory.
- [x] Public model-answer API path enforces load-bearing refusal before model calls and audits no-context or below-verified recalled items.
- [x] Credence audit entries are persisted to the main hash-chained audit journal by default on service ingest without storing item content.

## Phase 7 — Retrieval orchestrator

- [x] `recall()` returns ranked `KnowledgeItem` results with currency, provenance, dependencies, supersession, last verification, stale reasons, and token estimates.
- [x] `timeline(query, as_of)` reconstructs historical state from the event log.
- [x] Review mode surfaces stale/superseded items; default mode filters computed non-Live items.
- [x] Scope filters, basic dedupe, centrality weighting, credence weighting, and context budget controls exist.
- [x] Retrieval uses semantic vector scoring with stable hashed embeddings and legal-domain synonym expansion rather than token-set Jaccard search.
- [x] Ranking weights are calibrated by `tune_recall_weights()` over deterministic synthetic relevance/credence/centrality cases and documented in benchmarks.

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
- [x] Postgres server backend is implemented through `SOLOMON_DATABASE_URL`, with tenant services mapped to separate Postgres schemas and SQLite remaining the local default.
- [x] PyInstaller local binary and Docker Compose server config are built/verified in this worktree; evidence is recorded in `docs/release-artifacts.md`.
- [x] Server multi-tenancy now has a durable tenant registry, admin lifecycle endpoints, active/suspended state, tenant-specific API-key hashes, optional explicit provisioning, and isolated storage namespaces.

## Phase 11 — Headline demo: stale house-view

- [x] `examples/stale-house-view/run.py` creates the 2023 memo, 2025 authority change, 2026 query, Solomon flag, warehouse-baseline miss, boundary masking proof, and audit chain.
- [x] Demo uses the real vendored boundary, not a fake client.
- [x] Internal supersession example exists.
- [x] README GIF has been re-rendered with `scripts/render_stale_house_view_gif.py` and matches the committed asset.

## Phase 12 — Evaluation

- [x] Synthetic corpus generator exists and exports reproducible items, dependencies, changed authority, and oracle stale ids.
- [x] Evaluation harness now actually writes the corpus to store/graph/index, runs propagation, recall, warehouse baseline, decay baseline, and timing.
- [x] Metrics include stale-surface rate, time-to-flag, and impact-query recall.
- [x] Evaluation now includes executable jurisdiction-pack coverage and external-law monitoring fixture-replay benchmarks, alongside the synthetic currency corpus and baselines.
- [x] Boundary-fidelity evaluation runs an executable vendored-boundary suite covering sanitization, reidentification, leak checks, and volatile mapping flushes.

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
- [x] Server auth now requires an admin key, accepts bearer/API-key credentials, maps requests to scoped admin or tenant principals, stores tenant key hashes, and enforces route-level read/write/manage/diagnostics scopes.
- [x] Stored-knowledge hardening normalizes control characters, detects instruction-like content on ingest, records findings, marks unsafe content as instruction-role, and blocks it from load-bearing answers.

## Phase 16 — Repo docs

- [x] README, architecture, concepts, Kaypoh integration, trust boundary, benchmark/evaluation, and ADR docs exist.
- [x] Docs now describe the vendored boundary design and pinned source commit.
- [x] Generated OpenAPI has been refreshed after schema/API changes.
- [x] Launch/readme media is current: `docs/assets/stale-house-view-demo.gif` was re-rendered from the checked-in script.

## Phase 17 — Launch

- [x] Launch post, FAQ, outreach docs, packaging README, and citation metadata exist.
- [x] Annotated git tag `v0.1.0` is present in this worktree for the current release state.
- [x] Built pip artifacts and desktop binary are present in `dist/`: sdist, wheel, and `solomon-local`.
- [x] Early-user outreach and eval submission are externally tracked through the public GitHub `v0.1.0` release, attached release artifacts, and live GitHub issues #1-#5.
