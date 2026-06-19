# RFC-0001 Internals: Daemon Wire Protocol

RFC: [Daemon Wire Protocol](../../rfcs/0001-daemon-wire-protocol.md)

## Decision

Shisa uses length-prefixed UTF-8 JSON over a per-user Unix-domain `SOCK_STREAM` socket. Shell clients send one framed request, receive one framed response, and close the connection.

## Why

The prompt hook needs deterministic I/O with no partial-read ambiguity. A fixed `u32_be` payload length keeps clients small while preserving JSON debuggability.

## Implementation Notes

- Frame encode/decode lives under `src/proto/`.
- The request payload includes shell state such as cwd, exit code, duration, terminal size, color capability, glyph capability, uid, session, and request id.
- The daemon rejects oversized frames before allocating untrusted payloads.
- Local clients should treat daemon errors as recoverable and fall back to a cheap prompt.
