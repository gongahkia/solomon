# Learned Memory Policy

This is the gated plan for any learned policy that touches Shibahama memory
operations. The current implementation provides read-only gates for Stage 1,
Stage 2 planning, and Stage 3 readiness. It does not train a model, does not run
online learning, and does not apply candidate actions to storage.

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

Stage 1 is implemented as read-only evaluation in
`shibahama_core::learned_policy` and exposed through
`Shibahama::evaluate_offline_policy`. Reports include per-decision traces,
per-action summaries, aggregate candidate/baseline scores, invariant
violations, and a structured null result when the candidate cannot proceed.

Stage 2 is implemented only as a disabled-by-default shadow-experiment planner
through `plan_contextual_bandit_experiment` and
`Shibahama::plan_contextual_bandit_experiment`. It may propose bounded deltas to
existing `SignificanceConfig` weights after Stage 1 clears stricter evidence
gates. It does not update runtime configuration, does not learn online, and does
not ship a new model.

Stage 3 is implemented only as a readiness gate through
`assess_stage3_training_readiness` and
`Shibahama::assess_stage3_training_readiness`. It requires Stage 2 evidence plus
a written GPU/cost plan, dataset card, reward ablations, invariant property
tests, and held-out continuity evaluation. Passing this gate only allows offline
training research; runtime learned-policy deployment remains blocked.

## Null Result Rule

If the offline candidate does not beat the deterministic baseline without
violating invariants, the correct conclusion is:

> deterministic significance is sufficient; RL not justified

That result should be written up rather than hidden. For a real user-facing
product, not shipping a fragile learned policy is an acceptable outcome.

## Current Evaluation Artifact

The current committed Stage 1 local artifact is:

- `benchmarks/results/learned-policy-stage1-local.json`
- `benchmarks/results/learned-policy-stage1-local.md`

It uses the ContinuityBench v0 dataset hash
`sha256:a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa`
and a fixed four-decision held-out trace. The candidate score is `0.00`, the
deterministic baseline score is `2.25`, and the recommendation is
`StopBaselineNotBeaten`. The checked-in conclusion is: deterministic
significance is sufficient; RL not justified.

Invariant evidence is covered by:

```sh
python3 -m pytest benchmarks/test_learned_policy_artifact.py
```

## Stage 2 Status

Issue #9 is closed as not justified by the current Stage 1 artifact. The
held-out candidate did not beat deterministic significance, so no online
contextual-bandit runtime experiment should run. The Stage 2 planner remains a
disabled-by-default API gate only.

## Stage 3 Status

Issue #10 is closed as not started. Stage 3 requires Stage 1 and Stage 2 to
prove useful signal without invariant violations; the current Stage 1 artifact
does not beat deterministic significance, and Stage 2 is not justified. No
GRPO/PPO training setup, reward ablation, GPU plan, or runtime learned-policy
deployment is authorized.

## Current Non-Claims

- There is no online contextual-bandit loop in the product.
- There is no GRPO/PPO policy model in the product.
- There is no delete or overwrite action in the learned-policy action space.
- There is no learned-policy path that can bypass the deterministic never-delete,
  credence-floor, or provenance-lineage gates.
