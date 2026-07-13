# MCP error taxonomy

Status: v0.2 target contract

MCP protocol failures still use JSON-RPC errors. Solomon domain failures return structured tool results with `ok=false` unless the request is malformed enough to fail protocol validation.

## Error envelope

```json
{
  "ok": false,
  "error": {
    "code": "scope_denied",
    "message": "caller is not allowed to access this matter scope",
    "retryable": false,
    "details": {
      "matter_id": "matter-123"
    }
  }
}
```

Rules:

- `code` is stable and machine-readable.
- `message` is safe for client display.
- `retryable` is explicit.
- `details` never includes raw firm content, privileged text, mapping tables, or secrets.
- every error is audit-logged with tool name, caller, scope, and input hash.

`authorization_denied` covers a missing bound identity, an insufficient tool scope or role, an out-of-scope matter or
client, or a restricted caller requesting a global export. The response does not disclose the principal's permitted
scope set.

## Codes

### `boundary_rejected`

Meaning: Boundary review found PII/MNPI/privileged leakage risk or unsafe model-egress content.

Applies to: `preflight_context`, `ingest`, `audit_pack`, any future content-returning tool.

HTTP analogy: 422 / 451 depending on deployment policy.

Retryable: false unless caller narrows scope or removes unsafe content.

Details:

- `classification`
- `finding_count`
- `jurisdiction`
- `policy`

### `currency_unknown`

Meaning: Solomon cannot establish currency state for the item or authority. Usually caused by missing item, missing dependency data, or incomplete authority version metadata.

Applies to: `check_currency`, `preflight_context`, `impact`, `audit_pack`.

HTTP analogy: 404 if item missing, 409 if dependency state incomplete.

Retryable: false until data is ingested or linked.

Details:

- `knowledge_item_id`
- `external_authority_id`
- `missing`

### `scope_denied`

Meaning: Caller requested a matter/client/item outside the permitted MCP scope.

Applies to: all tools.

HTTP analogy: 403.

Retryable: false with the same credentials.

Details:

- `matter_id`
- `client_id`
- `knowledge_item_id`
- `caller_id`

### `model_routing_failure`

Meaning: A workflow needed a model endpoint, but routing failed because no allowed endpoint was available, zero-egress policy blocked remote use, local fallback was unavailable, or boundary sanitization failed closed before model call.

Applies to: future model-assisted dependency suggestions; any future MCP tool that invokes model routing.

HTTP analogy: 503.

Retryable: true only if endpoint health or policy config changes.

Details:

- `matter_sensitivity`
- `zero_egress_mode`
- `endpoint`
- `fallback_attempted`

### `verification_required`

Meaning: Requested context exists but is not safe to use as load-bearing context because it is stale-pending, superseded, retired, contested, unverified, or overdue for verification.

Applies to: `preflight_context`, `check_currency`, `audit_pack`.

HTTP analogy: 409.

Retryable: false until a human verification action changes the item state.

Details:

- `knowledge_item_id`
- `currency_state`
- `verified_state`
- `last_verified_at`
- `required_action`

## Protocol validation failures

Malformed JSON-RPC, missing required input fields, wrong enum values, invalid schema, and unknown tool names should fail as MCP/JSON-RPC request errors rather than domain envelopes. The audit journal still records an input hash and caller when available.

## Source of truth

The JSONSchema input/output contract lives in `src/solomon/mcp/schemas.py`. This doc defines stable domain codes and semantics for MCP handler implementation.
