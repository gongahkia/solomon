# Learned Memory Policy

This is the gated plan for any learned policy that touches Shibahama memory
operations. The current implementation is Stage 1 only: offline evaluation of
candidate decisions against logged human signals. It does not train a model,
does not run online learning, and does not apply candidate actions to storage.

## Why This Is Gated

The nearby literature is useful, but it optimizes for goals that can conflict
with Shibahama's invariants.

- [Memory-R1](https://arxiv.org/abs/2508.19828) trains memory management with
  operations including ADD, UPDATE, DELETE, and NOOP, using PPO/GRPO-style
  outcome optimization across memory and answer agents.
- [DeltaMem](https://arxiv.org/abs/2604.01560) frames persona memory management
  as an end-to-end agentic task and introduces operation-level update labels and
  a Memory-based Levenshtein Distance reward.
- [SEARL](https://arxiv.org/abs/2604.07791) jointly optimizes policy and
  tool-memory structures and explicitly addresses sparse outcome rewards by
  building structured experience memory.
- [MemRL](https://arxiv.org/abs/2601.03192) is adjacent: it learns utility over
  episodic memory through environmental feedback without updating model weights.

Those are valid research directions, but Shibahama is a user-facing memory
engine with a never-delete invariant, credence floors, provenance, and
append-only auditability. A policy that improves answer exact match by deleting
or overwriting inconvenient history is a regression here, not progress.

## Allowed Action Space

The Stage 1 evaluator accepts only non-destructive candidate actions:

- NOOP.
- Promote to a hotter tier.
- Demote to a colder tier, only if it does not violate the credence floor and
  does not target a floor-protected memory.
- Merge with provenance, where all source memory IDs are present and preserved
  as lineage.
- Flag for review.

There is no delete action and no overwrite action. The evaluator exposes this
action set through `ALLOWED_POLICY_ACTION_NAMES` and the `PolicyAction` enum in
`shibahama_core::learned_policy`.

## Reward Order

The evaluator is invariant-first:

1. Reject any action trace with a never-delete, floor, or provenance-lineage
   violation.
2. Reject evaluations with too few subsequent human labels.
3. Score the candidate policy and the deterministic significance baseline
   against the same labels.
4. Proceed only if the candidate beats the baseline by the configured margin.

Human labels come from existing append-only `HumanSignalRecorded` events:

- `Affirm` and `Pin` are positive labels.
- `Challenge` and `Correct` are negative labels.
- `Unpin` is neutral.

When a candidate decision has a `decided_at` timestamp, only later human signals
are labels. That keeps the Stage 1 question honest: would the candidate action
have predicted subsequent human judgment better than the hand-tuned baseline?

## Baseline

The baseline is deliberately simple and legible. It uses the current materialized
significance score:

- promote one tier when significance is at or above the configured promote
  threshold;
- demote one tier when significance is below the configured demote threshold,
  clamped by the memory's credence floor;
- otherwise NOOP.

This is not meant to be a strawman. It is the hand-tuned significance policy the
project already ships. A learned policy that cannot beat it offline should not
graduate to online experiments.

## Stage Gates

Stage 1 is now implemented as read-only evaluation in
`shibahama_core::learned_policy` and exposed through
`Shibahama::evaluate_offline_policy`.

Stage 2 remains unbuilt. It may only be a contextual-bandit experiment over the
existing significance weights, not a new model, and it must use contest-derived
reward with invariant violations as hard failures.

Stage 3 remains unbuilt. It requires Stage 1 and Stage 2 evidence, plus a written
GPU/data-volume plan, reward ablations, and property tests proving no invariant
violations across the action trace.

## Null Result Rule

If the offline candidate does not beat the deterministic baseline without
violating invariants, the correct conclusion is:

> deterministic significance is sufficient; RL not justified

That result should be written up rather than hidden. For a real user-facing
product, not shipping a fragile learned policy is an acceptable outcome.
