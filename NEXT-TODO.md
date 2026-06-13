# Shibahama — consolidation pass, human-in-the-loop "challenge", null-hypothesis honesty, and an RL stretch (TODO-only)

These are ADDITIVE features on top of the current fix-list. Implement Part 1 and
Part 2 for real. Document Part 3 thoroughly. Add Part 4 as TODO-only — do NOT
start building it; it depends on Parts 1–2 existing first.

Keep the core ethos intact throughout: never-delete invariant, credence floor,
usage-driven significance, and DX/legibility as priority #1. Nothing here may
violate never-delete.

## Part 1 — Offline consolidation pass ("the dream"), but LEGIBLE (first-class)
Context: the 2026 field has converged on offline memory consolidation (Karpathy's
LLM Wiki, Claude's "Dreams", Hermes background subagents). They all share one
property Shibahama already has — they generate a new consolidated view WITHOUT
destroying the original input data. The universal weakness: consolidation is an
opaque black box. Shibahama's differentiator is a consolidation pass that is
driven by the usage signal AND fully visible in the Tideline.

1. [x] Implement a `consolidate()` pass that runs offline / on idle, never on the hot
   recall path. It may: merge duplicate/fragmented memories into a synthesized
   higher-level memory; promote/demote tiers based on accumulated usage; flag
   stale-but-significant items for reconstruction. It may NOT delete or overwrite
   originals — consolidated memories are NEW items that link back to their
   sources (provenance preserved), and originals remain queryable.
2. [x] Drive consolidation decisions from the existing significance/usage signal and
   the credence floor — safety-critical / floored items must survive consolidation
   unchanged. Add a test asserting floored items are never merged away or demoted
   below floor by a consolidation pass.
3. [x] Emit a consolidation event for every decision (merge/promote/demote/flag) with
   a `why` trace: which inputs, what usage evidence, what was produced.
4. [x] Tideline: add a consolidation view that replays a pass — show memories merging,
   tiers shifting, items being flagged, each with its `why`. This is the headline
   DX moment; budget for it. Nobody has a legible consolidation pass.
5. [x] Make consolidation idempotent-safe: re-running on an unchanged store produces
   no spurious new memories.

## Part 2 — Human-in-the-loop "challenge" / override (first-class, generalisable)
Context: a real gap is that significance can't be fully objective — a human must
be able to weigh in. Build this with GENERAL agent-memory semantics (not legal
vocabulary): "challenge", "correct", "affirm", "pin".

6. [x] Add API verbs: `challenge(memory_id, reason)`, `affirm(memory_id)`,
   `correct(memory_id, proposed_content)`, `pin(memory_id)` / `unpin`.
   - challenge → lowers credence and flags the item for review; recorded as an
     access/usage event with negative outcome.
   - affirm → raises credence / refreshes verification; positive usage event.
   - correct → enters a proposed replacement at LOWER credence, quarantined,
     invalidate-not-delete the prior version on corroboration (reuse the Part-of-
     fix-list reconstruction pipeline).
   - pin → sets/raises the credence floor so the item cannot decay below it.
7. [x] Every challenge/affirm/correct/pin is an append-only audit event with actor +
   timestamp + reason. These are the legible human signals.
8. [x] Surface challenges in the Tideline (contested items visually marked; show the
   human reason alongside the machine significance).
9. [x] CRITICAL design note to encode in code comments + docs: these human signals
   are logged in an RL-ready shape (see Part 4) but are NOT wired into any reward
   or automatic policy in this shipped version. They affect credence/supersession
   directly and deterministically. Keep them decoupled from any learned policy.
10. [x] Tests: challenge lowers credence and never deletes; pin enforces floor;
    correct routes through quarantine+corroboration; all four emit audit events.

## Part 3 — Confront the null hypothesis HONESTLY (document heavily, in-repo)
Context: recent eval work shows simple retrieval can match or beat complex memory
hierarchies on LoCoMo/LongMemEval, and long-context models can sometimes bypass
memory structures entirely. Do NOT hide this. Owning it is more credible than
dodging it.

11. [x] Add `docs/null-hypothesis.md` that states the threat plainly: usage-aware
    reconstructive memory may not beat flat retrieval on standard one-shot QA
    accuracy. Then define precisely the regime where it SHOULD win and why:
    - continuity / repeated-use tasks where the same facts recur and CHANGE over
      time (currency), measured by stale-answer-rate and token-economics, not
      one-shot recall. (Cite the 2026 framing: memory is an economics/continuity
      win before an across-the-board recall win; "some agents improve from use".)
12. [x] Make the benchmark story match: position CurrencyBench + a continuity task as
    the home turf; report flat-retrieval baselines honestly even where they win on
    plain accuracy. The claim is "wins on stale-rate + tokens on continuity tasks",
    not "beats everyone on LoCoMo".
13. [x] Put a short, honest "When NOT to use Shibahama" section in the README (flat
    RAG is fine for stateless one-shot QA). This honesty is a feature.

## Part 4 — RL for memory operations (TODO-ONLY — do not build yet)
Add this as a clearly-marked future phase in TODO.md. It depends on Parts 1–2
shipping first (it needs the consolidation actions and the logged human
challenges). Write it rigorously and anti-sycophantically — flag the tension, do
not hand-wave it.

Add these as unchecked TODO items under a new "Phase: Learned memory policy
(stretch, gated)":
- [ ] Document the core tension explicitly: the dominant RL-for-memory paradigm
      (Memory-R1, DeltaMem, SEARL) learns an action space that INCLUDES DELETE and
      rewards on naked answer-correctness (Exact Match / QA). Both fight
      Shibahama's invariants: never-delete and credence floor. A rigorous version
      must (a) restrict the action space to non-destructive ops (NOOP / promote /
      demote / merge-with-provenance / flag — NO delete, NO overwrite), and
      (b) use a reward that cannot be gamed by discarding inconvenient memories.
- [ ] Stage 1 (laptop-feasible, gating): OFFLINE policy evaluation on the logged
      human challenges from Part 2. Question: would a learned demote/merge/flag
      policy have made better decisions than the hand-tuned significance function,
      judged against subsequent human affirms/challenges? No training loop. If the
      signal isn't there offline, STOP — do not proceed to training.
- [ ] Stage 2: contextual-bandit / online learning over the EXISTING significance
      weights (not a new model). Reward = contest-derived (affirm=+, challenge=−)
      with task-outcome as a secondary check, penalised for any floor violation or
      any attempt to demote a pinned/floored item. Compare against the hand-tuned
      baseline; ship only if it wins without violating invariants.
- [ ] Stage 3 (only if 1–2 prove out): small policy model trained with GRPO/PPO
      over the constrained non-destructive action space. Document infra needs
      honestly (GPU, training data volume from logged contests). Reward design must
      be written up and ablated, not assumed.
- [ ] Eval requirement for ALL stages: report whether the learned policy beats the
      hand-tuned significance function on a held-out continuity task, and PROVE it
      never violated never-delete / floor across the eval (property test over the
      action trace). No invariant violations is a hard gate, not a metric.
- [ ] Anti-sycophancy clause in the doc: if RL does not beat the deterministic
      baseline, the honest outcome is "deterministic significance is sufficient;
      RL not justified" — and that null result gets written up, not buried.

## Reconcile the TODO
14. Add the new shipped work (Parts 1–2) and the documentation work (Part 3) as
    honest, accurately-checked phases. Add Part 4 as the unchecked gated stretch
    phase. Do not over-check.

## Report back
What consolidation decisions the pass makes and how they appear in the Tideline;
the four human-signal verbs and their tests; the null-hypothesis doc; and the
RL stretch phase as TODO-only (confirm nothing in Part 4 was built).
