# MCP tool examples

Status: v0.2 target examples. IDs and authority names are fictional.

## `solomon.preflight_context`

Request:

```json
{
  "query": "Can we reuse the 2023 structure X view?",
  "matter_id": "matter-new-client",
  "client_id": "client-b",
  "max_items": 3,
  "caller_id": "mcp-host:alice"
}
```

Response:

```json
{
  "items": [
    {
      "item": {
        "id": "item-2026-001",
        "kind": "house-view",
        "content": "Structure X may be used only after MAS Notice 626 controls are re-checked.",
        "matter_id": "matter-new-client",
        "client_id": "client-b"
      },
      "currency": {
        "state": "live",
        "last_verified_at": "2026-05-21T09:00:00Z"
      },
      "dependencies": ["mas-notice-626"]
    }
  ],
  "excluded": [
    {
      "item_id": "item-2023-014",
      "reason": "stale-pending after MAS Notice 626 update",
      "code": "verification_required"
    }
  ],
  "scope": {
    "matter_id": "matter-new-client",
    "client_id": "client-b",
    "caller_id": "mcp-host:alice"
  },
  "boundary": {
    "status": "passed",
    "classification": "SAFE",
    "finding_count": 0,
    "context_id": "ctx-abc"
  },
  "audit": {
    "entry_hash": "sha256:preflight"
  }
}
```

## `solomon.check_currency`

Request:

```json
{
  "knowledge_item_id": "item-2023-014",
  "caller_id": "copilot:m365:alice"
}
```

Response:

```json
{
  "knowledge_item_id": "item-2023-014",
  "state": "stale_pending",
  "reasons": [
    {
      "dependency_id": "mas-notice-626",
      "changed_at": "2026-04-01T00:00:00Z",
      "reason": "external authority changed after last verification"
    }
  ],
  "last_verified_at": "2023-11-09T10:30:00Z",
  "verified_by": "partner-a",
  "successor_id": null
}
```

## `solomon.get_dependencies`

Request:

```json
{
  "knowledge_item_id": "item-2026-001",
  "direction": "both",
  "depth": 2
}
```

Response:

```json
{
  "knowledge_item_id": "item-2026-001",
  "upstream": [
    {
      "edge_id": "edge-1",
      "source_id": "item-2026-001",
      "target_id": "mas-notice-626",
      "target_kind": "external_authority"
    }
  ],
  "downstream": [
    {
      "edge_id": "edge-9",
      "source_id": "item-client-advice-88",
      "target_id": "item-2026-001",
      "target_kind": "internal_knowledge"
    }
  ],
  "truncated": false
}
```

## `solomon.verify_position`

Request:

```json
{
  "knowledge_item_id": "item-2023-014",
  "verifier_id": "partner-a",
  "decision": "supersede",
  "evidence_ref": "dms://memo/2026-05-structure-x",
  "successor_id": "item-2026-001",
  "recorded_at": "2026-05-21T09:00:00Z"
}
```

Response:

```json
{
  "item": {
    "id": "item-2023-014",
    "currency_state": "Superseded",
    "successor_id": "item-2026-001",
    "verified_by": "partner-a"
  },
  "currency": {
    "state": "superseded",
    "last_verified_at": "2026-05-21T09:00:00Z"
  },
  "audit": {
    "entry_hash": "sha256:verification"
  }
}
```

## `solomon.ingest`

Request:

```json
{
  "text": "Structure X may be used only after MAS Notice 626 controls are re-checked.",
  "source_ref": "dms://memo/2026-05-structure-x",
  "scope": {
    "matter_id": "matter-new-client",
    "client_id": "client-b",
    "jurisdiction": "sg"
  },
  "kind": "house-view",
  "source_kind": "partner",
  "author": "Partner A"
}
```

Response:

```json
{
  "item": {
    "id": "item-2026-001",
    "kind": "house-view",
    "currency_state": "Live",
    "verified_state": "Verified",
    "matter_id": "matter-new-client",
    "client_id": "client-b"
  },
  "boundary": {
    "status": "passed",
    "classification": "SAFE",
    "finding_count": 0,
    "context_id": null
  },
  "dependency_suggestions": [
    {
      "suggestion_id": "sug-1",
      "target_id": "mas-notice-626",
      "confidence": "model_suggested"
    }
  ],
  "audit": {
    "entry_hash": "sha256:ingest"
  }
}
```

## `solomon.audit_pack`

Request:

```json
{
  "knowledge_item_id": "item-2026-001",
  "format": "json"
}
```

Response:

```json
{
  "knowledge_item_id": "item-2026-001",
  "format": "json",
  "pack": {
    "provenance": {
      "source_ref": "dms://memo/2026-05-structure-x",
      "author": "Partner A"
    },
    "dependencies": ["mas-notice-626"],
    "verification_history": ["sha256:verification"],
    "boundary": {
      "classification": "SAFE"
    }
  },
  "hash_chain": {
    "valid": true,
    "head": "sha256:journal-head"
  }
}
```

## `solomon.dependency_suggestions`

Request:

```json
{
  "knowledge_item_id": "item-2026-001",
  "decision": "pending",
  "limit": 20
}
```

Response:

```json
{
  "suggestions": [
    {
      "suggestion_id": "sug-1",
      "item_id": "item-2026-001",
      "target_id": "mas-notice-626",
      "target_kind": "external_authority",
      "evidence": "MAS Notice 626 controls"
    }
  ],
  "scope": {
    "matter_id": "matter-new-client",
    "client_id": "client-b",
    "caller_id": null
  }
}
```

## `solomon.impact`

Request:

```json
{
  "external_authority_id": "mas-notice-626",
  "matter_id": "matter-new-client",
  "client_id": "client-b"
}
```

Response:

```json
{
  "external_authority_id": "mas-notice-626",
  "stale_item_ids": ["item-2023-014", "item-client-advice-88"],
  "reasons": {
    "item-2023-014": [
      {
        "dependency_id": "mas-notice-626",
        "reason": "authority changed after last verification"
      }
    ]
  },
  "scope": {
    "matter_id": "matter-new-client",
    "client_id": "client-b",
    "caller_id": null
  }
}
```
