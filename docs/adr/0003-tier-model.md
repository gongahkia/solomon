# ADR 0003: Tier Model

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama needs memories to become cheaper or more expensive to surface as their observed
usefulness changes. The system also must not permanently lose memory history. A pure ranking score
would be easy to implement but too weak for the product thesis; actual deletion would be too risky
for real users.

## Decision

Model memory accessibility with three tiers:

- `Hot`: high-significance, recent, cheap to surface in working context.
- `Warm`: indexed and normally searchable; the default tier for live memories.
- `Cold`: retained but intentionally expensive; excluded from default retrieval unless a caller opts
  into cold recall or a reconstruction path requests it.

Decay moves items toward colder tiers as significance falls. Reinforcement moves items toward hotter
tiers when access and outcome signals justify it. No tier transition deletes an item, its event log,
its provenance, or its historical versions.

Credence floors constrain tier demotion for classes of memory that must remain load-bearing, such as
explicit user instructions, authoritative project decisions, and rejected approaches the agent should
not re-suggest.

## Rationale

The tier model gives Shibahama real state transitions that can be inspected and visualized in the
Tideline without turning forgetting into data loss. Cold memories remain available for explicit,
cost-aware retrieval and reconstruction.

Keeping the tier as materialized state also makes APIs honest about cost: callers can tell whether a
candidate was resident, indexed, or pulled from cold storage.

## Consequences

- Tier transitions are domain events, not incidental cache mutations.
- Retrieval defaults must exclude cold items unless the caller opts in.
- Storage compaction may compress cold content later, but metadata and provenance remain readable.
- The never-delete invariant needs tests on storage, invalidation, compaction, and future eviction
  logic.
- The Tideline can replay tier transitions from the event log instead of inferring them from current
  state.
