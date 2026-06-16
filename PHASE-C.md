# Phase C — Standard Benchmarks: Hygiene, Done Honestly (LAST)

Referenced by `NEXT-TODO.md` items in the Phase C section (LongMemEval-S/LoCoMo
carried-forward `[!]` item, plus items 34–35).

## Purpose

LoCoMo and LongMemEval are the benchmarks the agent-memory field publishes
against. Their **absence** from Shibahama is a guaranteed interview question
("why no LoCoMo number?") and a credibility hole. Their **presence** is not the
differentiator — these are conversational-recall evals, and Shibahama's chosen
audience (coding agents, framework builders) and thesis (continuity/epistemic
governance) live elsewhere.

So this phase is **hygiene**: produce competitive, fully reproducible numbers,
report them honestly including where flat retrieval wins, and cross-reference
against Phase B so the real story ("competitive on standard recall, wins on
stale-rate/economics on continuity") is told with both halves present. Goal is
"we are not absent and our harness reproduces," NOT "we win the leaderboard."

## Context (so the agent calibrates expectations honestly)

The field's current published numbers are high and from funded teams who have
tuned extraction for a year:
- Mem0's 2026 algorithm reports ~92.5 on LoCoMo and ~94.4 on LongMemEval at under
  ~7k tokens/query.
- LoCoMo (~1,540 QA across single-hop/multi-hop/open-domain/temporal) and
  LongMemEval (~500 questions including knowledge-updates and multi-session) are
  the standard two; BEAM (1M/10M scale) is the harder, less-saturated third.
- Vendors benchmark on different datasets and dispute each other's configs
  (Mem0 vs Zep's LoCoMo numbers differ by ~10 points depending on who ran it).
  This means: report YOUR exact config and command so your number is
  reproducible and not a he-said-she-said.

Do not target a leaderboard-topping number. Target a credible, reproducible one,
and let Phase B carry the "we win here" weight.

## Deliverables (definition of done)

1. LoCoMo run from the official export → committed JSON + Markdown artifact.
2. LongMemEval-S run from the official export → committed JSON + Markdown
   artifact.
3. Both reports include the required baselines and full reproduction manifest.
4. At least one real external system (Mem0 OSS self-hosted) on the same slice,
   not just the strawman warehouse baseline.
5. A cross-reference section tying Phase C numbers to Phase B results.

## What each artifact must contain

For each benchmark (LoCoMo, LongMemEval-S), the committed report includes:

- Shibahama's accuracy (per the benchmark's own scoring), broken down by the
  benchmark's question categories (single-hop, multi-hop, temporal, open-domain
  for LoCoMo; the LongMemEval category set for that one).
- **Baselines on the identical slice**:
  - flat/warehouse retrieval (honest version, not the strawman),
  - full-context where reproducible,
  - at least one external system (Mem0 OSS) — item 34.
- Retrieval token cost per query for each system (the economics axis, consistent
  with Phase B).
- Stale-answer rate where the benchmark has knowledge-update questions
  (LongMemEval explicitly does) — this lets you connect to Phase B's central
  metric on a standard dataset.
- Full manifest: dataset hash, model, seed, exact command, embedding model,
  judge model + prompt hash if an LLM judge is used.

The loaders already exist (`docs/benchmarks.md:119-125`); this phase produces the
*artifacts* they were built to generate.

## Honesty requirements (the point of the phase)

- Report where the flat baseline or full-context **beats** Shibahama on plain
  one-shot accuracy. This is expected on stateless single-hop recall and owning
  it is more credible than hiding it. `docs/null-hypothesis.md` already commits to
  this framing — make the numbers match the doc.
- Do not cherry-pick the favorable benchmark. Run both. If one is unfavorable,
  that's reported, not dropped.
- Do not reconfigure baselines to be artificially weak. The flat baseline here is
  the same honest flat adapter as Phase B, not the warehouse-scores-0 strawman.
- If a number can't be reproduced by an external reader from the committed
  command + manifest, it's not done.

## Cross-reference (item 35)

A section (in each report or a shared `benchmarks/results/SUMMARY.md`) that states
plainly, with numbers from both phases:

- where Shibahama is **competitive** on standard recall (Phase C), and
- where it **wins** on stale-answer rate / token economics on continuity tasks
  (Phase B).

The pair is the honest, defensible story. Neither half alone is. The narrative an
interviewer should be able to read off the repo: *"On standard conversational
recall we're in the competitive band but not topping it — that race is
saturated. On continuity tasks, where facts change over time, we cut stale-answer
rate by X and token cost by Y versus flat retrieval, which is the regime our
architecture is built for and the one coding agents actually live in."*

## External baseline note (item 34)

The current benchmark suite compares Shibahama only against a warehouse baseline
that scores 0 — which reads as rigged to any reviewer. A self-hosted Mem0 OSS run
on the same continuity slice (and on LoCoMo/LongMemEval here) is the minimum
credible external anchor. Document the Mem0 version, config, and command. If Mem0
outperforms Shibahama on standard recall, report it — that's consistent with the
thesis and expected.

## Acceptance criteria

- [ ] LoCoMo artifact committed: JSON + MD, all baselines, full manifest,
      reproducible from the committed command.
- [ ] LongMemEval-S artifact committed: same requirements, including stale-answer
      rate on knowledge-update questions.
- [ ] At least one real external system (Mem0 OSS) present in both, not just the
      warehouse baseline.
- [ ] Reports show, not hide, where flat/full-context wins on plain accuracy.
- [ ] Cross-reference section present, citing both Phase B and Phase C numbers.
- [ ] Every number reproducible from its committed manifest + command by an
      external reader.

## Sequencing note

Runs LAST, after Phase A (perf) and Phase B (continuity). It reuses Phase B's
honest flat adapter and Mem0 adapter, and its token-cost methodology, so building
it after B is strictly less work. Some items here remain `[!]` blocked on
official dataset export access — note that blocker explicitly in any partial
result.
