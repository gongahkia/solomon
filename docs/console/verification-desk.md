# Verification Desk wireframe

Status: console screen 1 of 3

## Purpose

Let a KM lawyer review stale or contested knowledge, inspect evidence, and record a partner decision without leaving Solomon.

## Primary route

`GET /console/verification`

## Layout

```text
+----------------------------------------------------------------------------------+
| Solomon / Verification Desk                         [matter] [client] [refresh]   |
+-------------------------------+--------------------------------------------------+
| Inbox                         | Evidence preview                                 |
|                               |                                                  |
| [needs review] [contested]    | Item title / source_ref                          |
| [stale] [superseded]          | Currency: StalePendingReverification             |
|                               | Credence: Verified -> needs partner sign-off     |
| item id        reason   age   |                                                  |
| item-1         reg r    3d    | Knowledge excerpt                                |
| item-2         contest  1d    | Dependency / contest reasons                     |
| item-3         overdue  7d    | Provenance, source, author, dates                |
|                               | Audit hash / journal pointer                     |
|                               |                                                  |
|                               | Partner decision                                 |
|                               | [reaffirm] [supersede] [retire] [pin]            |
|                               | Evidence ref [________________________]          |
|                               | Successor id  [________________________]          |
|                               | Partner id    [________________________]          |
|                               | [submit decision]                                |
+-------------------------------+--------------------------------------------------+
```

## Inbox query

Initial implementation can derive the inbox from:

- `store.get_many()` filtered to `currency_state == StalePendingReverification`.
- `verified_state == NeedsReview`.
- items with `metadata.contests`.
- items with `metadata.staleness_reasons`.

Later implementation can add dedicated service methods if the filter grows.

## Row fields

- item id.
- kind.
- matter id.
- client id.
- source ref.
- currency state.
- verified state.
- highest-priority reason.
- last verified at.
- successor id if present.

## Evidence preview

Show:

- content excerpt, capped and escaped.
- provenance: source kind, source ref, author, matter.
- currency evaluation: state, explanation, stale reasons.
- dependencies and dependents from `why(item_id)`.
- contest metadata if present.
- current audit journal status and latest relevant audit hash if available.

Do not show raw boundary mappings.

## Actions

### Reaffirm

Service call:

`record_verification(item_id, VerificationRequest(outcome="reaffirm", by=partner_id))`

Required fields:

- partner id.
- evidence ref.

Effect:

- item returns to `Live`.
- `last_verified_at` and `verified_by` update.
- stale reasons clear in the currency engine path.

### Supersede

Service call:

`record_verification(item_id, VerificationRequest(outcome="supersede", by=partner_id, successor_id=successor_id))`

Required fields:

- partner id.
- evidence ref.
- successor id.

Effect:

- predecessor becomes `Superseded`.
- successor id is recorded.
- successor must already exist in this first version.

### Retire

Service call:

`record_verification(item_id, VerificationRequest(outcome="retire", by=partner_id))`

Required fields:

- partner id.
- evidence ref.

Effect:

- item becomes `Retired`.
- valid-to timestamp is closed.

### Pin

Service call:

`pin(item_id, PinRequest(lawyer_id=partner_id, reason=evidence_ref, actor_tier=FirmAuthoritative))`

Required fields:

- partner id.
- evidence ref or pin reason.

Effect:

- item gets a FirmAuthoritative credence floor.

## Form behavior

- `GET /console/verification/items?state=...` returns an inbox partial.
- `GET /console/verification/items/{item_id}` returns the evidence preview partial.
- `POST /console/verification/items/{item_id}/decision` applies one decision and returns updated row + preview.
- HTMX swaps only the row and preview panel.
- On validation errors, keep the form values and show field-level messages.

## Empty states

- No review items: show a compact "No pending verification" state and link to Dependency Review.
- Missing item: return a 404 partial and remove stale row from the inbox.
- Scope denied: show a non-sensitive denial message.

## Acceptance checks

- Stale item appears in inbox after authority-change propagation.
- Contested item appears with contest reason.
- Reaffirm removes item from stale filter.
- Supersede requires successor id.
- Retire removes item from default live recall.
- Pin requires FirmAuthoritative actor.
- Audit journal receives the verification/pin event.
