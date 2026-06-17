# RFC-0005: Wire Protocol v1

- Status: Accepted
- Created: 2026-06-17
- Owner: core maintainers
- Area: wire protocol

## Summary

This RFC is the canonical reference for Shisa protocol v1. It binds framing, JSON envelope fields, operation names, response shapes, error codes, and compatibility rules for shell clients, editor bridges, plugins, and scripts.

## Motivation

RFC-0001 established the daemon protocol shape. v1 now needs a stable consumer-facing reference so external integrations can generate clients without reading daemon internals.

## Design

Transport is a per-user Unix-domain `SOCK_STREAM` socket. Request/response ops use one request frame and one response frame per connection. `subscribe` starts with one framed request, then keeps the socket open and switches both directions to newline-delimited JSON.

Each frame is:

```text
u32_be payload_len
payload_len bytes of UTF-8 JSON
```

`payload_len` is capped at 1 MiB. Receivers must reject larger frames before allocating the payload.

All JSON payloads are objects. Unknown fields are ignored. Required common request fields:

| Field | Type | Notes |
| --- | --- | --- |
| `v` | integer | Must be `1`. |
| `op` | string | One v1 operation name. |
| `request_id` | string | Client-generated id echoed by the daemon. |

Render-family requests add shell state:

| Field | Type | Notes |
| --- | --- | --- |
| `cwd` | string | Absolute working directory. |
| `exit` | integer | Last command exit code. |
| `jobs` | integer | Background job count. |
| `duration_ms` | integer | Last command duration. |
| `time` | bool | Whether to render time module. |
| `no_async` | bool | Disable async placeholders for this render. |
| `shell` | string | `zsh`, `bash`, `fish`, `nu`, or `pwsh`. |
| `cols` | integer | Terminal columns. |
| `rows` | integer | Terminal rows. |
| `tty` | string | Terminal device path. |
| `color_caps` | string | `truecolor`, `256`, `16`, or `none`. |
| `glyph_caps` | string | `nerdfont`, `unicode`, or `ascii`. |
| `user_id` | integer | Local uid. |
| `session` | string | Shell session id. |

v1 operation names:

| Op | Request | Response |
| --- | --- | --- |
| `render` | render-family request | prompt response |
| `render_continue` | render-family request | prompt response |
| `health` | common request | health response |
| `metrics` | common request | metrics response |
| `reload` | common request | reload response |
| `version` | common request | version response |
| `subscribe` | common request plus topics | event stream |

Prompt response:

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

Health response:

```json
{ "v": 1, "request_id": "uuid-v4", "ok": true }
```

Metrics response includes `connections`, `cache`, and `fsnotify` objects. Metrics fields are additive and clients must ignore unknown keys.

Version response:

```json
{ "v": 1, "request_id": "uuid-v4", "daemon": "0.1.0-dev", "protocol": 1 }
```

Reload response:

```json
{
  "v": 1,
  "request_id": "uuid-v4",
  "reloaded": true,
  "config_generation": 2,
  "plugin_generation": 2,
  "plugins": 4
}
```

Subscribe request adds `topics: []string` and optional `backpressure_limit`. Duplicate topics increment a per-connection reference count. The daemon keeps a bounded per-connection event queue; events produced after that queue reaches `backpressure_limit` are dropped. The first daemon line is a snapshot event whose `data.refs` object maps each distinct topic to its reference count. Later daemon replies use NDJSON delta events, with monotonically increasing `data.sequence` values per connection. Client disconnect releases per-connection refs and pending events:

```json
{ "v": 1, "request_id": "uuid-v4", "topic": "vcs.summary", "kind": "snapshot", "data": {} }
```

Error responses use the envelope and codes documented in `docs/protocol/errors.md`.

## Performance

Warm `render` p99 target remains under 2 ms end-to-end. Framing validation is O(1). JSON parsing may allocate during v0.x, but protocol v1 consumers must not depend on field order or omitted optional fields.

## Security

The socket is per-user under a user-owned runtime directory. The daemon validates frame size before allocation, validates protocol version before dispatch, and returns `E_CAPABILITY_DENIED` when a plugin or client asks for a denied operation or capability.

## Compatibility

Protocol major `v` is required. Unknown major versions return `E_VERSION` with `highest_supported_version`. Minor v1 additions are optional fields or additive enum values on documented extension points. Clients and servers must ignore unknown object fields.

## Rejected Alternatives

- Reusing RFC-0001 as the canonical reference: it describes the initial design but not the complete v1 surface.
- Per-op binary payloads: lower overhead, but harder for shell hooks and editor bridges to debug.
- Long-lived sockets for every render: useful later, but v1 keeps shell renders one request per connection for simpler failure isolation.

## Unresolved Questions

- Whether `subscribe` remains on the daemon socket or moves to an editor-specific socket after Phase 16.
- Whether reload generation counters should split config, theme, plugin manifest, and plugin runtime state.
