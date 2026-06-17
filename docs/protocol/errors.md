# Protocol Errors

Protocol errors use the RFC-0001 error envelope:

```json
{
  "v": 1,
  "request_id": "uuid-v4",
  "error": {
    "code": "E_MALFORMED",
    "message": "human-readable summary",
    "context": {}
  }
}
```

`message` is for logs and UI. Clients must branch on `code` and optional `context` fields.

## Codes

| Code | Meaning | Retry | Context |
| --- | --- | --- | --- |
| `E_VERSION` | Request `v` is not supported by this daemon. | no | `field`, `highest_supported_version` |
| `E_OVERSIZE` | Frame or payload exceeds the protocol cap. | no | `max_frame_bytes` |
| `E_MALFORMED` | JSON is invalid, required fields are missing, or a field has the wrong type/value. | no | `field`, `expected` |
| `E_NOT_READY` | Daemon or requested data is not ready yet. | yes | `op`, `retry_after_ms` |
| `E_PLUGIN_TIMEOUT` | Plugin execution exceeded its budget. | maybe | `plugin`, `timeout_ms` |
| `E_CAPABILITY_DENIED` | Plugin or client requested a denied capability. | no | `capability`, `op` |
| `E_READONLY` | Subscribe/editor connection attempted a mutating operation. | no | `op` |
| `E_INTERNAL` | Unexpected daemon failure after request parsing. | maybe | `detail` |

## Context Fields

| Field | Type | Notes |
| --- | --- | --- |
| `field` | string | Request or envelope field that caused the error. |
| `expected` | string | Expected type, enum value, or value range. |
| `highest_supported_version` | integer | Highest protocol major supported by the daemon. |
| `max_frame_bytes` | integer | Maximum accepted frame payload bytes. |
| `op` | string | Operation being handled. |
| `retry_after_ms` | integer | Minimum client backoff before retry. |
| `plugin` | string | Plugin id or manifest name. |
| `timeout_ms` | integer | Budget that was exceeded. |
| `capability` | string | Capability name denied by policy. |
| `detail` | string | Stable, non-secret diagnostic token. |

Unknown context fields are forward-compatible and must be ignored by clients.
