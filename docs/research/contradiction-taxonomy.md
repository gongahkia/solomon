# Contradiction Taxonomy

Solomon treats contradiction detection as a review trigger, not legal adjudication. The detector records why two firm knowledge items cannot both be relied on without human review.

## In Scope

1. Same-authority, opposite-conclusion positions.
   Two live `position` items cite the same external authority and carry opposite structured `conclusion_polarity` values. This is implemented deterministically from the dependency graph plus ingest metadata.

2. Newer live position negates an older live position in the same matter or client scope.
   This requires a confirmed shared topic/scope and a structured negation signal. It is not implemented in W16 because free-text negation without scoped conclusions would create false positives.

3. Position contradicts a confirmed supersession.
   A live item conflicts with an already confirmed `supersedes` relation. This is a future detector because it needs a richer supersession fact model than the current predecessor/successor edge.

## Out Of Scope

- Full semantic legal reasoning across arbitrary memo text.
- Determining which position is legally correct.
- Inferring missing authorities from unstructured text without a confirmed dependency edge.
- Cross-client contradiction claims unless a caller explicitly runs an unscoped detection pass.

## Current Detector

W16 implements detector (1):

- input: live `position` items with `metadata.conclusion_polarity` set to `affirmative` or `negative`;
- graph condition: both positions have a live `internal_depends_on_external` edge to the same authority id;
- exclusion: item/successor pairs do not produce contradiction signals;
- output: symmetric `ContradictionSignal` records, one per item direction;
- effect: both items are marked `StalePendingReverification` and `NeedsReview`;
- audit: each signal is appended as `contradiction_detected`, and each affected item gets a verification-requested lifecycle event.

An LLM classifier could later suggest `conclusion` and `conclusion_polarity` at ingest time, but the authoritative W16 path is structured and deterministic.
