# ADR 0005: Significance Function v0

- Status: Accepted
- Date: 2026-06-11

## Context

Shibahama's thesis depends on usage as a ranking and tiering signal. The first implementation needs
to be explainable, deterministic, and tunable without requiring training data. A learned scorer would
be premature and would make the Tideline harder to trust.

## Decision

Implement significance v0 as a transparent hand-tuned function:

```text
significance =
  base_score
  * time_decay(age_since_last_reinforcing_access)
  + reinforcement(access_count)
  + outcome_bonus(weighted_outcomes)
  + graph_bonus(centrality)
  - contradiction_penalty
```

The exact coefficients live in configuration. The default function must return an explanation
breakdown that can be surfaced by `why(memory_id)` and the Tideline.

The scorer is recomputed lazily on access, recall, reinforcement, or explicit explanation. Recall
refreshes candidate significance before ranking. The `Surfaced` event from the current recall is
recorded after the final candidates are chosen, so that access affects later recalls. There is no
global maintenance scan.

## Rationale

This keeps the first product honest. Users can inspect why a memory is hot, stale, demoted, or still
protected by a floor. Deterministic scoring also makes benchmarks and regression tests meaningful.

The function is intentionally not learned. Shibahama may later add learned parameters, but only after
the benchmark harness proves which signals matter.

## Consequences

- Every score-changing input must be represented as stored data or a deterministic derived value.
- The `why` API must expose the same terms used by the scorer.
- Config changes can change future rankings, so benchmark runs must log scoring config.
- Access-event capture is part of correctness, not optional observability.
- The scoring function should be replaceable behind a trait once the v0 contract is stable.
