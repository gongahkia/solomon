# OSC Sequences

Shisa emits standard terminal OSC sequences only when a prompt path needs them. Custom sequences are project-reserved until a consumer ships.

## OSC-7 Cwd

`shisa prompt` emits OSC-7 before the rendered prompt:

```text
ESC ] 7 ; file://<host><cwd> BEL
```

`<cwd>` is an absolute path with URI percent-encoding.

## Reserved A11y Summary

Shisa reserves OSC 9183 for a future accessibility summary channel:

```text
ESC ] 9183 ; a11y-summary ; v=1 ; <payload> BEL
```

`<payload>` is base64url without padding. The decoded bytes are UTF-8 JSON:

```json
{
  "text": "repo main, prod context, exit 1",
  "segments": [
    { "id": "cwd", "text": "repo" },
    { "id": "risk_tier", "text": "prod", "priority": "critical" },
    { "id": "exit_status", "text": "exit 1", "priority": "warning" }
  ]
}
```

Rules:

- Producers may terminate with BEL or ST (`ESC \`).
- Consumers must ignore unknown JSON fields.
- Producers must not embed raw control bytes in decoded JSON strings.
- Producers must keep encoded payloads at or below 4096 bytes.
- Producers must apply the same redaction policy used for rendered prompt text.
- Terminals are not expected to implement OSC 9183 directly; screen-reader bridges and plugins may consume it.

This sequence is reserved only. Core prompt rendering does not emit it yet.
