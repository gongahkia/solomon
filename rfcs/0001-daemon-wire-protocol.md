# RFC-0001: Daemon Wire Protocol

- Status: Accepted
- Created: 2026-06-15
- Owner: core maintainers
- Area: wire protocol

## Summary

Shisa v1 uses length-prefixed JSON over a per-user Unix-domain `SOCK_STREAM` socket. The shell client opens one connection per request, sends one frame, receives one frame, and closes.

## Motivation

The shell hook must be small and predictable. A framed request/response protocol avoids partial-read ambiguity while keeping early clients debuggable with ordinary JSON tooling.

## Design

Each frame is:

```text
u32_be payload_len
payload_len bytes of UTF-8 JSON
```

The maximum payload is 1 MiB. Oversized frames are rejected with an error frame when enough state exists to reply.

Every request includes:

```json
{
  "v": 1,
  "op": "render",
  "shell": "zsh",
  "cwd": "/abs/path",
  "exit": 0,
  "jobs": 0,
  "duration_ms": 1234,
  "cols": 200,
  "rows": 50,
  "tty": "/dev/ttys001",
  "color_caps": "truecolor",
  "glyph_caps": "unicode",
  "user_id": 501,
  "session": "uuid-v4",
  "request_id": "uuid-v4"
}
```

Every successful response includes:

```json
{
  "v": 1,
  "request_id": "uuid-v4",
  "prompt": "ansi string",
  "redraw_token": null,
  "trailer": null,
  "diagnostics": [],
  "elapsed_us": 1234
}
```

Errors use:

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

Initial ops:

- `render`: return the best prompt for the supplied shell state.
- `render_continue`: replace placeholders associated with a `redraw_token`.
- `health`: return minimal daemon readiness.
- `metrics`: return cache, render, and plugin counters.
- `reload`: reload config and plugin manifests.
- `version`: return daemon and protocol versions.
- `subscribe`: stream read-only editor updates.

Initial error codes:

- `E_VERSION`
- `E_OVERSIZE`
- `E_MALFORMED`
- `E_NOT_READY`
- `E_PLUGIN_TIMEOUT`
- `E_CAPABILITY_DENIED`
- `E_INTERNAL`

## Versioning

The `v` field is required. The daemon rejects unknown major versions with `E_VERSION` and includes the highest supported major in `context`. Minor additions are represented by optional fields; clients and servers ignore unknown fields.

## Performance

Warm `render` p99 budget is 2 ms end-to-end. The encoder and decoder must avoid hot-path heap allocation after session arenas are initialized.

## Security

The socket is per-user and created under a 0700 user-owned runtime directory. The daemon validates payload length before allocation and validates required fields before dispatch.

## Compatibility

The shell hook owns request-shape compatibility. During v0.x, breaking changes are allowed only when the hook and daemon update together. v1.0 freezes protocol major version 1.

## Rejected Alternatives

- NDJSON: simpler to inspect, but newline escaping and partial reads are weaker under arbitrary payloads.
- MessagePack: smaller, but worse for early debugging and hand-written shell clients.
- Multiplexed long-lived requests: useful later, but too complex for the v1 hot path.

## Unresolved Questions

- Whether `subscribe` remains in protocol v1 or moves to a dedicated editor socket.
- Whether payload cap should become configurable for editor integrations.
