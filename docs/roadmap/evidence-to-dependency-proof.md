<!-- SPDX-License-Identifier: Apache-2.0 -->

# Evidence-to-Dependency Proof

## Product risk and boundary

Solomon is a self-hosted provenance and change-impact control plane for high-stakes AI systems, initially applied
to internal legal knowledge. Its Currency Loop Proof begins with a reviewed dependency edge. This milestone proves
the preceding, deliberately narrower question: whether source evidence can create useful **candidates** without
turning a parser or model inference into firm knowledge.

The rule is **Suggest, do not silently trust.** Solomon still follows **Flag, do not adjudicate.** A citation can be
present in an internal document without supporting the position, and a dependency signal only asks a human to
review downstream knowledge after an authority change; it does not decide legal correctness.

| Object | Meaning | Can affect currency? |
| --- | --- | --- |
| Extracted reference | Text resembles an authority reference. | No |
| Dependency suggestion | Local deterministic extraction found a reliance cue and a cited authority in reviewable evidence. | No |
| Confirmed dependency | An authorized curator accepted the proposed relationship. | Yes |
| Rejected suggestion | A curator decided the proposal must not become an edge. | No |
| Deferred suggestion | A curator left the proposal unresolved pending more context. | No |

A mention is not a candidate dependency merely because it names an authority. The deterministic path now requires a
positive reliance cue in the same source sentence and rejects local negation, contrast, background, or distinguishing
cues. This is a review-budget heuristic, not a legal conclusion or a claim of comprehensive citation interpretation.

## Trust, scope, and evidence model

Source-document ingestion remains boundary-gated. Candidate claims are extracted from a reviewed source document;
a curator promotes a candidate claim to an internal `KnowledgeItem`; only then can local deterministic extraction
create a dependency suggestion. The optional LLM path still receives boundary-sanitized context and never confirms
an edge. Deterministic citation parsing runs locally after boundary preflight so its offsets reconstruct the stored
source evidence; it does not send raw text to a model endpoint.

Suggestions remain proposals at their source-derived credence. Creation and confirmation do not promote an item to
`Verified` or `FirmAuthoritative`. A confirmed edge has `human_confirmed` confidence, a curator actor, and a
`source_suggestion_id`; provenance therefore remains attached to the edge that can later trigger currency review.

Each persisted suggestion carries a deterministic fingerprint, source knowledge item, candidate authority,
normalized reference, extraction method, explanation, source-document identity/version and prior-version pointer
when available, source and authority spans, matter/client scope, decision state/actor/timestamp/reason, and audit
correlation. Tenant storage remains isolated by the existing per-tenant service directory or PostgreSQL schema.
Matter/client filters apply to suggestion listing and a decision that supplies a scope must match the source item.

## Lifecycle and idempotency

```text
pending → confirmed
pending → rejected
pending → deferred → confirmed | rejected
```

- Only `confirmed` calls `GraphStore.add_dependency`; `pending`, `rejected`, and `deferred` never create an edge.
- Confirming a confirmed suggestion and rejecting or deferring the same terminal/current decision are idempotent.
  A conflicting decision after confirmation/rejection fails explicitly rather than silently rewriting history.
- The graph store de-duplicates a source item/target/edge type. Re-running extraction on unchanged evidence finds the
  durable prior decision, so rejected evidence does not immediately reappear.
- The source-document store returns the existing document and candidate claims for unchanged bytes. A changed source
  writes a new document version with `previous_version_id`; promotion creates a new source item and a suggestion
  that points to that document lineage.
- Audit events record suggestion creation and each human decision with actor and correlation metadata. Audit packs
  verify the hash chain, but are not an externally anchored immutable ledger.

Confirmation is a `curate` operation through the existing service authorization layer. The local development service
retains its existing in-process identity; deployments must configure the existing server/OIDC or API-key policy.
This proof does not add an authentication mechanism.

## Versioned synthetic corpus and evaluation

The redistributable corpus is `examples/scenarios/evidence-to-dependency-proof/corpus/manifest.json`.
It is Apache-2.0 synthetic material: fictional organizations, authorities, matters, clients, and internal positions.
It contains stable IDs, scope metadata, source-document versions, ground-truth relationship labels, source/target
span text, development/locked-holdout splits, and a canonical manifest SHA-256. It includes exact and alias citation
forms, section references, multiple and similar authorities, direct/qualified/contrary/background/quotation/negated
references, malformed and ambiguous references, instruction-like source text, revisions, duplicate ingestion,
cross-scope lookalikes, potential transitive knowledge, and no-authority cases.

The labels are evaluation-only: `Depends`, `Mentions only`, `Contradicts or distinguishes`, `Ambiguous`, and `No
relationship`. They do not create production graph-edge types.

`scripts/evaluate_evidence_to_dependency.py` reports reference detection and dependency suggestion precision/recall
separately, exact and overlap/containment evidence spans, abstention correctness, duplicate rate, scope leakage,
pre-review edge creation, repeated-run determinism, runtime, and pipeline-stage error counts. It never persists a
suggestion, confirms an edge, calls a remote model, or aggregates metrics into a single accuracy score.

### Baseline before changes

The baseline was recorded from `0665993` behaviour before citation normalization, reliance gating, evidence-span
fields, or lifecycle changes. The output is `benchmarks/results/evidence-to-dependency-baseline.json` and
`docs/roadmap/evidence-to-dependency-baseline.md`: 23 items; authority-reference precision/recall `0.0/0.0`;
suggestion precision/recall `0.0/0.0`; exact and overlap evidence spans `0.0/0.0`; abstention correctness `0.333333`;
duplicate rate `0.0`; scope leakage `0`; and confirmed edges before review `0`. Its error distribution was reference
not detected `22`, candidate target not resolved `12`, candidate not generated `12`, and mention mistaken for
reliance `8`. The zero reference scores were caused by canonical-label mismatch: the old grammar discarded authority
titles and aliases. The baseline also suggested every parsed authority/section regardless of relationship context.

### Measured hypotheses retained

1. **Canonical title, alias, section-symbol, and neutral-citation normalization** targets the baseline reference
   normalization/resolution errors. It retains authority titles, maps `Reg.`/`s.`/`§` forms, preserves the existing
   eyecite result for conventional citations, and bounds neutral case citations.
2. **Same-sentence reliance cue plus inspectable spans** targets mention-as-reliance and missing-evidence errors.
   It adds local positive/negative cues and records the reviewed source sentence plus exact authority span.
3. **Multiple-reference and local contrast handling** targets collapsed candidates and false targets in sentences
   such as “A rather than B.” It keeps independently cited authorities separate and suppresses only the contrasted
   candidate.

All three were first measured on the development split and retained only because the locked holdout also remained at
`1.0` precision, recall, exact-span match, overlap/containment, and abstention correctness; duplicate rate stayed
`0.0`, scope leakage stayed `0`, and confirmed edges before review stayed `0`. The committed results at
`benchmarks/results/evidence-to-dependency-development.json`,
`benchmarks/results/evidence-to-dependency-holdout.json`, and
`benchmarks/results/evidence-to-dependency-final.json` are reproducible. These perfect scores describe only 23 deliberately controlled fixtures and must not be generalized
to real firm documents, legal authorities, or external curator behavior.

## Canonical headless workflow

Run the deterministic proof without a network or model:

```bash
uv run python examples/scenarios/evidence-to-dependency-proof/run.py --workspace /tmp/solomon-evidence-to-dependency-proof
```

It ingests synthetic source evidence; promotes three candidate internal claims; shows source and authority spans;
confirms a valid suggestion; rejects a quotation-derived mention; defers one unresolved suggestion; re-ingests the
unchanged document without duplication; restarts with decisions intact; ingests a revised document with suggestion
lineage; denies a mismatched matter decision; changes the authority; and verifies its audit pack. The normalized
snapshot is committed at `tests/fixtures/evidence-to-dependency-proof-snapshot.json` and checked by
`tests/test_evidence_to_dependency_demo.py`.

The authority change makes exactly the confirmed edge's item stale. Rejected and deferred suggestions remain edge-free
and live. That result feeds the existing [Currency Loop Proof](currency-loop-proof.md): after confirmation, the
established change → bounded propagation → review → re-verification lifecycle applies unchanged.

## Acceptance, interfaces, and non-goals

The existing service/REST/CLI interfaces expose suggestion retrieval and decisions. `GET /dependencies/suggestions`
accepts matter/client filters; `POST /dependencies/suggestions/{id}/confirm`, `/reject`, and `/defer` use the same
decision request; and `solomon defer-dependency-suggestion` is the CLI equivalent. MCP remains a scoped read surface
for suggestions; no duplicate business logic or named-host feature was added.

Acceptance requires manifest verification, deterministic development/holdout evaluation, durable and auditable
pending/confirmed/rejected/deferred states, idempotent unchanged ingestion and decisions, suppression after rejection,
document lineage after revision, scope-filtered retrieval and decisions, inspectable spans, no pre-review edge,
confirmed-edge-only propagation, audit-pack verification, and no Currency Loop regression. The proof and domain tests
exercise SQLite; the existing fake PostgreSQL graph-store path and disposable real PostgreSQL/pgvector integration are
release verification.

Non-goals: comprehensive legal dependency extraction, authority monitoring, legal reasoning or adjudication,
automatic confirmation, remote-model dependency, a new review framework, a new UI, additional jurisdictions, tenant
identity redesign, production adoption claims, and external curator validation.

Known limits: sentence-level cues are intentionally conservative and can abstain on valid reliance; deterministic
normalization is not a legal citation resolver; span offsets point to extracted text and may need human source-context
review; source encryption, retention, and deployment controls remain operator responsibilities; and synthetic scores
are not a usability, confidentiality, or legal-quality study.
