# Governed dependency assertion API

This additive REST surface records an explicit dependency assertion for review. It does not infer a relationship or
assess legal, factual, or semantic correctness. A record remains non-operative until an eligible reviewer confirms
it. The generated machine contract is [`openapi.json`](./openapi.json).

## Create and inspect

`POST /dependencies/assertions` accepts a `DependencyAssertionCreateRequest` and returns the persisted assertion.
The request binds one source `item_id` to its exact registered `source_document_id` and
`source_document_version`. The source document must be the immutable version in the item's source provenance.

```json
{
  "item_id": "position-alpha",
  "source_document_id": "source-document-alpha-v1",
  "source_document_version": 1,
  "target_kind": "external_authority",
  "authority_source_id": "official-gazette-alpha",
  "authority_identifier": "Regulation-R-12",
  "assertion_type": "normative_policy",
  "evidence_kind": "quote",
  "quote": "We rely on Regulation R section 12.",
  "quote_start": 0,
  "quote_end": 35,
  "rationale": "curator-recorded dependency for review",
  "created_by": "curator-alpha",
  "idempotency_key": "alpha-r12-v1",
  "origin": "human"
}
```

Allowed `assertion_type` values are `normative_policy`, `factual_evidence`, `procedural`, `derived_from`, and
`configuration_implementation`. The directional relationship is always `source item → target`; no reverse edge is
implied. `target_kind=knowledge_item` requires only an in-scope `target_item_id`. `target_kind=external_authority`
requires only a registered `authority_source_id` and `authority_identifier`, which becomes a canonical target ID.
Arbitrary target strings are rejected.

Quote evidence requires `quote`, `quote_start`, and `quote_end`; the service checks that slicing the stored immutable
source content by those offsets equals the quote exactly. Commentary evidence requires `commentary` and forbids all
quote fields. A `trusted_upstream` origin additionally requires `trusted_upstream_ref`; a human origin cannot supply
that field. Repeating the same origin/idempotency key returns the existing assertion only when the immutable request
digest matches; a mismatched retry is a conflict.

Use `GET /dependencies/assertions/{assertion_id}` for one record, or
`GET /dependencies/assertions/{assertion_id}/history` for the assertion projection, its graph events, and all audit
entries sharing its correlation ID. `GET /dependencies/assertions` returns `{ "items": [...], "next_cursor": ... }`.
It accepts `item_id`, `origin`, `state`, `target_id`, `creator`, `needs_reverification`, `matter_id`, `client_id`,
`limit`, and `cursor`. The cursor is the last returned assertion ID.

## Review and lifecycle

`POST /dependencies/assertions/{assertion_id}/decision` accepts `by`, `decision`, optional `reason`, optional
`expected_state_version`, and optional scope fields. Decision is `confirmed`, `rejected`, or `deferred`; a deferred
decision requires a reason. Confirmation is the only transition that creates a graph edge. Concurrent or retried
confirmations return the same edge, whose `source_suggestion_id` identifies the assertion. Rejected and withdrawn
assertions cannot be confirmed.

`POST /dependencies/assertions/{assertion_id}/withdraw` accepts `by`, `reason`, optional `expected_state_version`,
and optional scope fields. It withdraws pending or deferred assertions only; confirmed assertions require a traced
replacement rather than removal. A replacement can use `revision_of` at creation to link it to an earlier assertion.
Source-document revision marks existing records `needs_reverification` without changing their preserved evidence or
deleting a confirmed historical edge.

## Authorization and error shape

Create and withdraw require the `curate` service permission; decision requires `review`; list, get, and history
require `read`. The creator cannot decide their own assertion. Source and target scopes must agree on both matter and
client, and scoped reads/mutations outside that boundary use the service's non-disclosing not-found/denial response.
Malformed request shape, evidence, source binding, or invalid lifecycle transitions are rejected as bad requests;
missing registered records are not found; reuse of an idempotency key with different request data or a stale expected
state version is a conflict. Consult the generated OpenAPI contract for status-code envelopes and fields.
