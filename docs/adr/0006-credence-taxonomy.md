# ADR 0006: Credence Taxonomy and Floor

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama stores memories from users, agents, files, tools, web sources, and reconstruction steps.
Those sources do not deserve equal trust. Treating all retrieved text as equivalent would make the
memory store an injection surface and would let low-quality observations outrank explicit user or
project decisions.

## Decision

Use four generic open-source credence tiers:

- `FirmAuthoritative`: explicit user instruction, pinned project decision, or other source the caller
  marks as authoritative.
- `VerifiedSource`: observed from a source Shibahama can re-read or verify, such as a repository file,
  tool result, or signed/known provenance.
- `ModelInferred`: inferred by an agent or model from context rather than directly asserted by a
  trusted source.
- `Unverified`: web, imported, reconstructed, or otherwise unconfirmed content.

Each memory item also has a `credence_floor`: the coldest tier/accessibility class below which decay
and low significance cannot push it. The floor protects load-bearing negative memories and explicit
decisions from fading into practical invisibility.

Retrieval ranking must respect credence. Low-credence items may be surfaced, but they cannot outrank
conflicting authoritative items solely because they are more semantically similar or recently used.

## Rationale

Credence is separate from significance. A memory can be frequently accessed and still untrusted; a
rarely accessed explicit rejection may still need to remain available. Keeping those axes separate is
the simplest way to prevent usage reinforcement from laundering weak provenance into authority.

## Consequences

- Ingestion must assign credence from provenance by default.
- APIs must expose credence and provenance on every recall candidate.
- Reconstructed updates enter at lower credence until corroborated.
- Contradiction handling must compare credence before deciding which item is current.
- Tests must prove low-credence content cannot outrank contradictory authoritative content by score
  alone.
