# Solomon MCP tool surface

Status: v0.2 target contract  
Back end: `SolomonService` plus `solomon.currency`, `solomon.graph`, `solomon.audit`, and boundary APIs

## Contract rules

- Tool names are stable and namespaced as `solomon.*`.
- Every tool accepts `caller_id` when available from auth/session context; stdio clients may omit it.
- Every tool touching firm content accepts optional `matter_id` and `client_id` unless it targets a single existing item.
- Every returned firm-content field must pass boundary review before leaving MCP.
- Read tools return JSON objects, not free text.
- Write tools return the changed object plus audit metadata.
- Domain failures use structured error codes from `docs/mcp/errors.md` once implemented.

## Tools

### `solomon.preflight_context`

Purpose: Return current, non-stale firm context safe to inject into a model prompt.

Read/write: read

Backing API: `SolomonService.recall(RecallRequest(..., review_mode=False))`, then boundary preflight before return.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `query` | string | yes | user/model retrieval need |
| `matter_id` | string | no | restricts recall scope |
| `client_id` | string | no | restricts recall scope |
| `max_items` | integer | no | maps to recall `limit`; default 5 |
| `max_context_tokens` | integer | no | maps to recall token budget |

Output:

| Field | Type | Notes |
|---|---|---|
| `items` | array | current context entries, each with item, currency, provenance, dependencies |
| `excluded` | array | stale/scope/boundary exclusions, if known |
| `scope` | object | effective `matter_id`, `client_id`, caller |
| `boundary` | object | review outcome metadata, no raw mapping table |
| `audit` | object | audit entry id/hash when available |

### `solomon.check_currency`

Purpose: Return item currency state and reasons.

Read/write: read

Backing API: `SolomonService.evaluate_currency(knowledge_item_id)`.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `knowledge_item_id` | string | yes | item id |
| `as_of` | string | no | ISO-8601 timestamp for historical evaluation |

Output:

| Field | Type | Notes |
|---|---|---|
| `knowledge_item_id` | string | item id |
| `state` | enum | `live`, `stale_pending`, `superseded`, or `retired` |
| `reasons` | array | engine reasons and moved dependencies |
| `last_verified_at` | string/null | source item verification timestamp |
| `verified_by` | string/null | verifier id |
| `successor_id` | string/null | present for superseded items |

### `solomon.get_dependencies`

Purpose: Return upstream/downstream dependency edges for an item.

Read/write: read

Backing API: `SolomonService.why(...)` and graph store dependency/dependent reads.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `knowledge_item_id` | string | yes | item id |
| `direction` | enum | no | `upstream`, `downstream`, `both`; default `both` |
| `depth` | integer | no | traversal depth; default 1 |

Output:

| Field | Type | Notes |
|---|---|---|
| `knowledge_item_id` | string | root id |
| `upstream` | array | dependencies this item relies on |
| `downstream` | array | dependents relying on this item |
| `truncated` | boolean | true if depth/limit cut traversal |

### `solomon.verify_position`

Purpose: Record a human verification decision with evidence.

Read/write: write

Backing API: `SolomonService.record_verification(...)`; MCP wrapper adds evidence metadata to audit.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `knowledge_item_id` | string | yes | item id |
| `verifier_id` | string | yes | human/account id |
| `decision` | enum | yes | `reaffirm`, `supersede`, `retire`, `pin` |
| `evidence_ref` | string | yes | source pointer, doc id, URL, or audit reference |
| `successor_id` | string | no | required for `supersede` when successor already exists |
| `recorded_at` | string | no | ISO-8601 timestamp |

Output:

| Field | Type | Notes |
|---|---|---|
| `item` | object | updated knowledge item |
| `currency` | object | post-verification currency evaluation |
| `audit` | object | verification audit entry / attestation metadata |

### `solomon.ingest`

Purpose: Boundary-checked ingestion of new firm knowledge.

Read/write: write

Backing API: `SolomonService.ingest(IngestRequest(...))`.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `text` | string | yes | raw knowledge text |
| `source_ref` | string | yes | source id/path/URL |
| `scope` | object | yes | contains `matter_id`, `client_id`, optional jurisdiction |
| `kind` | string | no | default `note` |
| `source_kind` | string | no | default `associate` |
| `author` | string | no | human/source name |

Output:

| Field | Type | Notes |
|---|---|---|
| `item` | object | ingested `KnowledgeItem` |
| `boundary` | object | ingest review outcome |
| `dependency_suggestions` | array | proposed edges created on ingest |
| `audit` | object | ingest audit metadata |

### `solomon.audit_pack`

Purpose: Export provenance, dependency, verification, boundary, and hash-chain evidence for one knowledge item.

Read/write: read/export

Backing API: `SolomonService.export_audit_pack(...)` plus item filter over journal/store data.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `knowledge_item_id` | string | yes | item id |
| `format` | enum | no | `json` or `pdf`; default `json` |

Output:

| Field | Type | Notes |
|---|---|---|
| `knowledge_item_id` | string | item id |
| `format` | string | export format |
| `pack` | object/string | JSON object or generated file reference |
| `hash_chain` | object | journal verification metadata |

### `solomon.currency_report`

Purpose: Return partner-facing currency movements for a scope and period.

Read/write: read/export

Backing API: `SolomonService.currency_report(...)`, reading knowledge events plus current graph/currency state.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `period_start` | string | yes | ISO-8601 start timestamp |
| `period_end` | string | yes | ISO-8601 end timestamp |
| `scope` | enum | no | `firm`, `practice_area`, or `matter`; default `firm` |
| `practice_area` | string | no | required for practice-area scope |
| `matter_id` | string | no | required for matter scope |
| `client_id` | string | no | optional client filter |
| `format` | enum | no | `json`, `pdf`, or `pack`; default `json` |

Output:

| Field | Type | Notes |
|---|---|---|
| `report` | object | stale, contradictory, superseded, and retired movement rows |
| `pack` | object/null | audit-pack manifest/report JSON when `format=pack` |
| `pdf_base64` | string/null | human-readable PDF bytes when `format=pdf` |
| `hash_chain` | object | MCP call audit hash |

### `solomon.dependency_suggestions`

Purpose: Return proposed dependency edges for human confirmation.

Read/write: read

Backing API: `SolomonService.dependency_suggestions(...)`.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `knowledge_item_id` | string | yes | item id |
| `decision` | enum | no | default `pending`; may support `confirmed`/`rejected` |
| `limit` | integer | no | default 100 |

Output:

| Field | Type | Notes |
|---|---|---|
| `suggestions` | array | suggested edges, confidence, evidence snippets |
| `scope` | object | item matter/client scope |

### `solomon.impact`

Purpose: Return internal items affected by a changed external authority.

Read/write: read

Backing API: `SolomonService.impact_query(external_authority_id)`.

Input:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `external_authority_id` | string | yes | authority id / canonical ref |
| `as_of` | string | no | ISO-8601 timestamp |
| `matter_id` | string | no | optional output filter |
| `client_id` | string | no | optional output filter |

Output:

| Field | Type | Notes |
|---|---|---|
| `external_authority_id` | string | authority id |
| `stale_item_ids` | array | impacted internal item ids |
| `reasons` | object | dependency path and currency reason per item |
| `scope` | object | effective filters |

## Implementation notes

[Inference] The MCP layer should stay thin: validate schema, enforce auth/scope/rate limits, run boundary preflight, call `SolomonService`, write MCP audit metadata, and serialize. Currency, graph traversal, dependency suggestion, and audit-pack assembly remain owned by existing Solomon modules.
