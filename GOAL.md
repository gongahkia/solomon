# Shibahama — close the loop, build real reconstruction, stop overclaiming proof

## Context
Shibahama stays a clean standalone repo — no Kaypoh, no vendoring. These fixes
are about making the thesis real end-to-end and the proof honest.

## Priority 1 — Build the real end-to-end reconstruction API
1. Reconstruction currently exists only as primitives (the PlainRead gate works,
   but there's no assembled flow). Build the explicit pipeline:
   recall flags a stale/load-bearing candidate -> explicit revalidate (read the
   source/tool) -> quarantine the proposed update at lower credence -> require
   corroboration -> on corroboration, invalidate-not-delete the old version and
   write the replacement. Add an end-to-end test that exercises the whole chain.

## Priority 2 — Fix significance semantics and actually close the loop
2. Decide and document whether significance refresh happens BEFORE ranking (so
   the current recall reflects access history) or only AFTER access (so it
   affects later recalls). Right now recall() ranks on pre-access significance
   and records access afterward, so the loop never affects the current result —
   make this a deliberate, documented choice, not an accident.
3. Make significance recompute idempotent and purely derived from
   (base + access log). It's currently partly self-referential
   (significance.rs:182). Same access history must always yield the same score.
4. Wire lazy decay: if the design says "decay at access," recall() must call
   refresh_significance() at the right point. If it doesn't need to, document why.

## Priority 3 — Make the proof honest (a reviewer hits this first)
5. The all-system benchmark is overclaimed: Mem0/Zep/LoCoMo/LongMemEval are not
   actually run (missing deps, no ZEP_API_KEY), and the checked-in coding-agent
   benchmark scores 0/0 for both systems. Either: install Mem0, configure Zep,
   and run them for real; OR remove the adapters and claim only CurrencyBench.
   Do NOT keep a checked-in benchmark that reports 0 accuracy.
6. Expand CurrencyBench beyond the current 4 JSONL cases — it's a smoke test, not
   a benchmark. Aim for a corpus size that produces a defensible result.
7. The Tideline demo recording is synthetic demo_step data. Either generate it
   from a real engine run or label it clearly as illustrative.

## Priority 4 — Bi-temporal correctness
8. timeline() reads current materialized rows (storage.rs:1208), so late/backdated
   invalidations aren't event-time reconstructive. Make timeline reconstruct from
   the event log so a backdated invalidation is reflected correctly. Test with a
   backdated-invalidation case.

## Priority 5 — Real property tests
9. The TODO calls them "property tests" but they're deterministic unit tests, and
   there's no proptest/quickcheck dependency. Add real property-based tests for:
   never-delete, invalidated items excluded from default recall, and credence
   ordering — over generated operation sequences. Fix the mislabel in the TODO.

## Reconcile the TODO
10. Many boxes are checked but partial. Uncheck to ground truth and annotate
    partials honestly (e.g. "reconstruction: primitives only, no end-to-end
    engine"; "significance: materialized, partly self-referential"). An accurate
    TODO with visible gaps beats a fully-checked one that fails clone-and-run.

## Report back
List: the reconstruction end-to-end test result, the documented significance
decision, which benchmarks now produce real numbers vs were removed, the
backdated-timeline test result, and the reconciled TODO state.
