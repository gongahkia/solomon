<!-- SPDX-License-Identifier: Apache-2.0 -->

# Governed Dependency Assertion Proof Protocol

## Decision and threat boundary

This protocol defines a bounded way to record a human or trusted-upstream assertion that one registered knowledge
item depends on one registered authority or knowledge item. It is a control-plane record, not a legal conclusion,
authority resolver, document-management system, or semantic interpretation engine.

The threat addressed is an unreviewed, ambiguous, cross-scope, or unreconstructible dependency becoming an active
graph edge and changing the currency of internal knowledge. The central rule is:

> Solomon preserves, scopes, reviews, and propagates explicitly asserted dependencies with reconstructible evidence and audit provenance.

That statement does not claim that an assertion is legally correct, complete, authoritative, or semantically valid.
It does not make a parser or LLM output an assertion. The deterministic parser remains frozen at `a21263c`; the
rejected conservative-reliance experiment is retained only as historical evidence.

## Starting architecture and observed baseline

At protocol lock (`6778876`), Solomon already has one durable `DependencySuggestion` review lifecycle backed by
SQLite and PostgreSQL graph stores. It persists a JSON projection plus append-oriented suggestion events; it records
the originating knowledge item, target, decision, source-document/span metadata, scope, decision provenance, and
audit correlation. A confirmation creates a bi-temporal `DependencyEdge`; pending, rejected, and deferred records do
not. `SourceDocument` versions are append-oriented and retain a content SHA-256 and previous-version pointer. The
audit journal is metadata-only, append-only JSONL with a verifiable hash chain. Existing REST, CLI, and scoped MCP
read surfaces expose suggestions.

Before implementation, the following focused baseline passed on this checkout:

```text
uv run pytest -q tests/test_dependency_capture.py tests/test_evidence_to_dependency_proof.py \
  tests/test_currency_loop_proof.py tests/test_audit.py tests/test_audit_attribution.py \
  tests/test_service_authorization.py tests/test_api_source_workflow.py tests/test_api_client_cli.py \
  tests/test_cli.py tests/test_mcp_authorization.py tests/test_mcp_runtime.py tests/test_migrations.py \
  tests/test_postgres_backend.py
# 91 passed in 30.53s

SOLOMON_TEST_POSTGRES_DSN=postgresql://…@localhost:55432/solomon \
  uv run pytest -q tests/test_migrations.py tests/test_postgres_live_integration.py
# 6 passed in 0.59s (disposable pgvector/PostgreSQL 16)
```

The production change therefore extends the existing suggestion lifecycle rather than creating a parallel assertion
graph, a new inference language, or a second authorization path.

## Governed record contract

An explicit assertion is a `DependencySuggestion` with an explicit origin (`human` or `trusted_upstream`), a bounded
assertion type, and governed evidence. Existing `deterministic` and `llm` suggestions retain their current semantics
and are not upgraded by this work.

| Field | Required contract |
| --- | --- |
| source item | Existing `KnowledgeItem` ID. It supplies the assertion matter/client scope. |
| source document version | Existing registered `DocumentSource` and exact immutable `SourceDocument` ID/version, bound to the source item’s documented provenance. |
| target | Either an existing in-scope knowledge-item ID or a canonical authority ID obtained from a registered authority source and identifier. A free-text target is rejected. |
| relationship | One directional type: `normative_policy`, `factual_evidence`, `procedural`, `derived_from`, or `configuration_implementation`. Direction is always `source item → target`; no symmetric edge is implied. |
| evidence | Either exact quote evidence with raw offsets and raw quoted text reconstructible from the supplied source version, or commentary evidence explicitly marked semantic commentary. Commentary is never represented as a quote. |
| rationale and provenance | Non-empty rationale; authenticated/declared creator; creation time; correlation ID; audit event ID; origin and optional trusted-upstream reference. |
| lifecycle | `pending`, `confirmed`, `rejected`, `deferred`, or `withdrawn`. The immutable event history retains every prior state and revision pointer. |
| re-verification | Source revision marks an assertion for re-verification without rewriting its old evidence or deleting a prior confirmed edge. |

For quote evidence, `0 <= start < end <= len(source_document.content)` and slicing the exact stored source version must
equal both the supplied quote and the stored evidence. Missing, fabricated, non-contiguous, or ambiguous offsets are
rejected. Commentary requires no offsets but must state why it is semantic commentary. A source document must be
registered and readable before persistence. Source and target scope are compared before persistence; external
authorities are tenant-registered canonical targets and inherit the source item’s scope, while an internal target must
match both matter and client. Assertions cannot bridge two non-equal scoped knowledge items.

The durable projection includes immutable assertion ID, origin, creator, source-version identity/content hash, target
identity, scope, idempotency key, evidence, and assertion type. A confirmation edge carries the assertion ID in
`source_suggestion_id`; the database permits at most one current edge for one confirmed assertion. A revision creates
a new assertion linked to its predecessor; it never rewrites raw evidence, event history, or an old edge.

## Lifecycle, authorization, and concurrency

```text
create → pending ──confirm──> confirmed → source revision → needs reverification
                  ├─reject──> rejected
                  ├─defer───> deferred ──confirm/reject/withdraw──> terminal state
                  └─withdraw> withdrawn
```

- Creation, rejection, deferral, withdrawal, and source revision create no dependency edge.
- Only authorized confirmation creates one `human_confirmed` edge and may invalidate currency calculations.
- Retried create with the same idempotency key returns the original assertion only when its immutable request digest
  matches; a mismatched retry is rejected. Repeated or concurrent confirmation returns the same edge.
- A rejected or withdrawn assertion cannot be confirmed. A new assertion must use a new ID/idempotency key and has a
  traceable predecessor or explicitly distinct evidence.
- Separation of duties is enabled by default: the creator cannot confirm their own human/trusted assertion. A local
  compatibility override is explicit, records the override in audit metadata, and is not enabled by the proof.
- Service authorization remains centralized. Create/withdraw require `curate`; confirm/reject/defer require
  `review`; list/get/history/MCP inspect require `read`. Server routing enforces tenant scope first, then the service
  compares matter/client scope. Unauthorized create, read, listing, get, decision, and withdraw fail before mutation
  and receive the same non-disclosing not-found/denial shape as other scoped resources.
- The audit journal is append-only and public to the authorized audit-pack reader. Every creation, review, edge,
  revision, re-verification, currency-impact decision, authorization decision, and separation-of-duties denial has
  an event/correlation/actor reference. The journal is tamper-evident, not an externally anchored ledger.

## Public interface contract

The REST surface is additive and paginated: create `POST /dependencies/assertions`; inspect
`GET /dependencies/assertions/{id}`; list `GET /dependencies/assertions` with `item_id`, `origin`, `state`,
`target_id`, `creator`, `needs_reverification`, `matter_id`, and `client_id` filters; decision through the existing
decision semantics; withdraw; and history/edge-linkage inspection. Error responses use existing Solomon error
envelopes. Create accepts an idempotency key and optional `revision_of` predecessor link; decision and withdrawal
reject stale state-version tokens.

The CLI is non-interactive and stable-JSON: `assert-dependency`, `dependency-assertion`, `dependency-assertions`,
`decide-dependency-assertion`, and `withdraw-dependency-assertion`. Creation supports flags and one JSON request file.
The maintained Python HTTP SDK receives matching synchronous/asynchronous methods. MCP remains read-only: its
existing scoped dependency inspection grows a confirmed-assertion provenance projection only; it does not create,
decide, withdraw, infer, or symmetrically mutate assertions. The TypeScript MCP SDK is updated only for that read
projection.

## Proof scenario and acceptance gates

The deterministic, model-free, vendor-neutral headless scenario must use two scopes and several registered document
and authority sources. Its concise JSON result must show all of the following:

1. a human quote assertion, a semantic-commentary assertion, and a trusted-upstream assertion;
2. no edge at creation; confirmation of exactly one assertion; rejection of another; deferral and eligible withdrawal;
3. rejection of malformed quote offsets, free-text/nonexistent targets, and a cross-scope target before persistence;
4. denial of out-of-scope list/get/decision/withdraw and denial of creator self-confirmation;
5. idempotent retry and concurrent confirmation with one edge; no unconfirmed assertion affects currency;
6. source revision marks re-verification while prior assertion/evidence/history and old edge remain reconstructible;
7. audit IDs for creation, review, edge, revision, re-verification, and currency impact; and a verified audit pack.

Acceptance is all-or-nothing for these invariants: SQLite and real PostgreSQL schema behavior; source/target/scope
validation; exact quote reconstruction; commentary distinction; bounded types and transitions; withdrawal;
separation of duties; idempotent create/confirm; concurrent confirmation; edge provenance; revisions/re-verification;
audit-pack verification; REST/CLI/SDK/MCP read coverage; and the scenario. Regression gates are unchanged parser
source, the locked 23 and 84 fixture outcomes, the historical rejected 64-fixture corpus, existing currency-loop
scenarios, no unconfirmed currency effect, no cross-scope records, no unreviewed edges, at least 90% coverage, lint,
type checks, security/dependency audit, documentation build, package/Helm/Compose/binary release checks where the
repository provides them.

## Explicit non-goals and limits

This milestone does not tune, revive, or add parser language; automatically confirm an assertion; call an LLM;
declare legal or semantic correctness; validate authorities against an external legal database; provide a new
authentication system; make MCP mutable; delete evidence or historical edges; or establish production adoption.
Source documents currently remain in the existing SQLite document store even when graph/knowledge storage uses
PostgreSQL, so cross-store atomicity is not claimed. The implementation must compensate with validation, durable
idempotency, and recovery-safe event order, and the proof must label that boundary clearly.

The recommended completion action is a bounded owner-operated pilot, measuring only observed review behavior and
operator feedback. A failed safety gate preserves this protocol and evidence, reverts unsafe code, and records the
specific blocker rather than widening parser semantics.
