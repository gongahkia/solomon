# RFC-0005 Internals: Wire Protocol v1

RFC: [Wire Protocol v1](../../rfcs/0005-wire-protocol-v1.md)

> Historical note: this page records the original v1 design. The active daemon
> protocol is v2; its breaking change moves configuration and theme selection
> out of prompt requests and into the daemon runtime snapshot.

## Decision

Protocol v2 is the stable consumer-facing wire contract for shell clients, editor bridges, plugins, and scripts.

## Why

RFC-0001 defined the initial transport. RFC-0005 fixes the versioned request/response shape so integrations do not need to read daemon internals.

## Implementation Notes

- Request and response schemas live in `docs/protocol/v2.schema.json`.
- Request/response ops use length-prefixed JSON frames.
- `context` returns only daemon-cached local state; it does not start probes or grant capabilities.
- `subscribe` starts with one framed request, then switches to newline-delimited JSON on the open socket.
- Unknown fields are ignored for forward compatibility.
- Error responses use the documented protocol error codes in `docs/protocol/errors.md`.
