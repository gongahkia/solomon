<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cross-Boundary Operation Matrix

This inventory records the implemented write paths. `K/G/O` means the selected knowledge/graph/operation backend;
`S` source SQLite; `W` workflow/authority SQLite; `A` append-only audit JSONL. Each row names separate persistence
boundaries, not one atomic transaction. The service fixes the tenant before exposing a matter/client selector.
Matter/client is an exact operational filter; server tenant isolation is the authorization boundary.

| Workflow and initiator | Authoritative write | Derived writes / interruption state | Detection and recovery | Compensation / operator view |
| --- | --- | --- | --- | --- |
| Document creation (`ingest_source_document`, sync) | S document version plus source change event | candidates, A encryption/ingest event; crash can omit candidates/audit | source version/change event with candidate/audit operation mismatch; regenerate deterministic candidates and audit | no deletion; inspect version/change/operation |
| Document revision/tombstone (`write_document`, sync) | S successor version/change event | G assertion `needs_reverification`, A event | prior/replacement linkage without reverification operation; enqueue deterministic revision operation | preserve old evidence/edge; ambiguous lineage is operator-required |
| Evidence ingestion / candidate promotion (`ingest`, `promote_candidate_claim`) | K knowledge event/current state with immutable source-candidate ID | retrieval index, deterministic suggestions, S promoted candidate marker, A/credence records | knowledge item without expected index/suggestion/audit checkpoint or completed candidate operation without its SQLite marker | rebuild index/suggestions only from stored item; rescan candidate ID to complete one promotion; inspect content hash and source provenance |
| Dependency-suggestion generation (`suggest_dependencies`) | K item plus O deterministic-generation request | G pending suggestion record, A created event | operation absent/pending or its graph/audit checkpoint absent | rescan item or replay deterministic generation, never confirm it; non-replayable LLM suggestion requests are refused in this profile |
| Human confirmation of parser suggestion | O reviewed suggestion-confirmation request | G confirmed suggestion then one edge, currency/cache, A decision | operation/checkpoint or confirmed-origin edge mismatch | safe retry reads the confirmed suggestion and edge; rejected suggestions cannot be scheduled or repaired into an edge |
| Assertion creation (`create_dependency_assertion`) | journaled authorized request, then G assertion | A created event | operation/assertion/audit linkage check | retry creation only with request digest/idempotency match; inspect creator/evidence/scope |
| Assertion confirmation (`decide … confirmed`) | journaled reviewed confirmation intent | G edge + confirmed assertion, contradiction/cache, A review/edge records | valid confirmation operation missing edge/checkpoint/audit; edge without valid confirmed assertion is unsafe | safe edge recreation only for still-confirmed provenance-valid assertion; otherwise operator |
| Rejection, deferral, withdrawal | G assertion transition | A transition event | transition/audit operation mismatch | replay only same terminal/non-edge state; never compensate into edge |
| Confirmed graph-edge creation | G unique `source_suggestion_id` edge | G confirmation state, cache/contradiction, A edge link | duplicate/missing/orphan edge finding | unique constraint/idempotent reread; orphan/invalid provenance requires operator |
| Authority revision/supersession (`register_authority_change`, poll) | W authority event/idempotency record or K supersession event | K currency state, W review tasks, A impact/event | authority event or change ID missing item impact/task/audit checkpoint | idempotent change-ID propagation; inspect task/event/impact |
| Currency-impact propagation | K stale current-state/event per affected item | cache invalidation, A lifecycle/impact | confirmed edge/change operation missing expected staleness reason; stale currency projection | rerun same change ID; no automatic reversal of historical stale event |
| Audit-event recording | respective durable domain/journal operation checkpoint | A hash-chained entry and audit pack contents | expected operation/result ID absent from A; A entry references missing result | append idempotently by operation phase; hash-chain corruption/operator intervention |
| Audit-pack generation | existing verified A journal and referenced records | copied pack/manifest/artifact hashes | pack verification or referenced operation/result lookup fails | regenerate only from durable records; never alter journal evidence |

Implemented recovery details: evidence ingestion, deterministic suggestion generation, assertion creation and
non-confirming transitions have durable audit operations; unprocessed authority workflow events, source evidence,
knowledge items, assertions, and source revisions are rescanned before the worker drains eligible operations.
Confirmation uses graph, currency, and audit checkpoints. Retry is bounded to three worker attempts with exponential
delay; `terminal_failed` stays visible and may be scoped-requeued, while `operator_required` is deliberately refused
until an operator resolves the provenance, authorization, or lineage ambiguity.
