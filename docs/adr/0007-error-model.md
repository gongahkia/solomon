# ADR 0007: Error Model and Graceful Degradation

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama sits in the critical path of agent context assembly. Errors must be actionable for
developers and safe for users. A recall query may partially succeed even if a vector backend, graph
expansion, or reconstruction hook fails. Conversely, write-path failures must not pretend a memory
was persisted.

## Decision

Use stable typed errors with an explicit severity:

- Recoverable: the operation can return a partial result or a degraded answer with warnings.
- Fatal: the requested operation cannot be completed without violating durability, temporal,
  credence, or never-delete guarantees.

Writes, invalidations, and event-log appends fail closed. If Shibahama cannot durably append the
source event and update materialized state consistently, the write returns a fatal error.

Recall degrades explicitly. If one retrieval stage fails, Shibahama may return candidates from the
successful stages only when the response includes degradation metadata that names the failed stage.
`why` must include any degradation that affected the candidate.

## Rationale

Silent fallback is dangerous in memory systems: it can make stale, incomplete, or low-credence
results appear authoritative. Typed degradation preserves developer ergonomics while keeping failure
visible.

The write path has a higher bar because Shibahama's core safety promise depends on event-log
durability and never deleting history.

## Consequences

- Public bindings must preserve structured error codes, not collapse everything to strings.
- Recall results need a warning/degradation field.
- Tests must cover write atomicity failures and partial recall failures.
- Server mode maps typed errors to HTTP/gRPC status codes without losing Shibahama error codes.
- Error messages should name the failed invariant and the operation the caller can retry or change.
