<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cross-Boundary Operation Matrix

This inventory records the pre-milestone write paths and the required journal/projection treatment. `K/G` means the
selected knowledge/graph backend; `S` source SQLite; `W` workflow/authority SQLite; `A` audit JSONL. All inspection
is matter/client scoped through the source knowledge record and must return non-disclosing absence for another scope.

| Workflow and initiator | Authoritative write | Derived writes / interruption state | Detection and recovery | Compensation / operator view |
| --- | --- | --- | --- | --- |
| Document creation (`ingest_source_document`, sync) | S document version plus source change event | candidates, A encryption/ingest event; crash can omit candidates/audit | source version/change event with candidate/audit operation mismatch; regenerate deterministic candidates and audit | no deletion; inspect version/change/operation |
| Document revision/tombstone (`write_document`, sync) | S successor version/change event | G assertion `needs_reverification`, A event | prior/replacement linkage without reverification operation; enqueue deterministic revision operation | preserve old evidence/edge; ambiguous lineage is operator-required |
| Evidence ingestion (`ingest`) | K knowledge event/current state | retrieval index, deterministic suggestions, A/credence records | knowledge item without expected index/suggestion/audit checkpoint | rebuild index/suggestions only from stored item; inspect content hash and source provenance |
| Dependency-suggestion generation (`suggest_dependencies`) | G pending suggestion record | A created event | suggestion without operation audit or expected extraction checkpoint | replay deterministic generation, never confirm it |
| Assertion creation (`create_dependency_assertion`) | journaled authorized request, then G assertion | A created event | operation/assertion/audit linkage check | retry creation only with request digest/idempotency match; inspect creator/evidence/scope |
| Assertion confirmation (`decide … confirmed`) | journaled reviewed confirmation intent | G edge + confirmed assertion, contradiction/cache, A review/edge records | valid confirmation operation missing edge/checkpoint/audit; edge without valid confirmed assertion is unsafe | safe edge recreation only for still-confirmed provenance-valid assertion; otherwise operator |
| Rejection, deferral, withdrawal | G assertion transition | A transition event | transition/audit operation mismatch | replay only same terminal/non-edge state; never compensate into edge |
| Confirmed graph-edge creation | G unique `source_suggestion_id` edge | G confirmation state, cache/contradiction, A edge link | duplicate/missing/orphan edge finding | unique constraint/idempotent reread; orphan/invalid provenance requires operator |
| Authority revision/supersession (`register_authority_change`, poll) | W authority event/idempotency record or K supersession event | K currency state, W review tasks, A impact/event | authority event or change ID missing item impact/task/audit checkpoint | idempotent change-ID propagation; inspect task/event/impact |
| Currency-impact propagation | K stale current-state/event per affected item | cache invalidation, A lifecycle/impact | confirmed edge/change operation missing expected staleness reason; stale currency projection | rerun same change ID; no automatic reversal of historical stale event |
| Audit-event recording | respective durable domain/journal operation checkpoint | A hash-chained entry and audit pack contents | expected operation/result ID absent from A; A entry references missing result | append idempotently by operation phase; hash-chain corruption/operator intervention |
| Audit-pack generation | existing verified A journal and referenced records | copied pack/manifest/artifact hashes | pack verification or referenced operation/result lookup fails | regenerate only from durable records; never alter journal evidence |

Current retry before this milestone is uneven: SQLite knowledge and authority polling have durable outboxes, authority
events are deduplicated, governed assertions have request/edge uniqueness, and currency propagation uses a change
ID. Source documents, assertion audit appends, source revision reverification, and mixed-store projection order have
no unified durable recovery record. The operation journal, inspector, and guarded repair close those gaps without
describing their separate writes as atomic.
