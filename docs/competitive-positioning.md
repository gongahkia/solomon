# Competitive Positioning

As of July 2, 2026, Shibahama should be positioned as a local, inspectable
memory substrate for coding agents and framework builders. It is not currently a
LoCoMo or LongMemEval leaderboard play.

## Short Version

Shibahama competes on epistemic governance and continuity:

- append-only memory history with soft invalidation, never silent overwrite;
- credence floors and human signal verbs for reviewable trust changes;
- bi-temporal recall, timeline replay, audit, and Tideline inspection;
- local Rust core with Python, Node, CLI, and optional HTTP surfaces.

Use that framing against systems optimized for conversational recall accuracy,
hosted context engineering, or agent framework ergonomics.

## Evidence In This Repo

Phase B is the strongest current artifact. On the checked-in ContinuityBench
summary, Shibahama records stale-answer rate `0.375`, contradiction accuracy
`1.000`, credence/evidence rho `1.000`, and mean retrieved tokens `10.620`.
The same table reports Mem0 OSS exact-event retrieval at stale-answer rate
`0.812`, contradiction accuracy `0.140`, and mean tokens `13.425`; Engram exact
retrieval at stale-answer rate `0.475`, contradiction accuracy `0.680`, and
mean tokens `12.290`; full-context ties stale-answer rate and contradiction
accuracy but costs `13.425` tokens.

Phase A is honest but not yet a win claim. The checked-in perf summary reports
local recall p50 around `62-72 ms` from 1k to 100k items and explicitly says the
run does not prove sub-millisecond recall or tier-latency benefit. Keep using
Phase A as reproducibility evidence, not as a speed superiority claim.

Phase C now has checked-in official LoCoMo and LongMemEval-S artifacts. They do
not support standard benchmark superiority: full-context and warehouse beat
Shibahama on both plain-recall slices, and Mem0 OSS also beats Shibahama on
LongMemEval-S.

Sources in repo:

- `benchmarks/results/continuity/SUMMARY.md`
- `benchmarks/results/perf/README.md`
- `docs/benchmarks.md`
- `docs/null-hypothesis.md`

## Vs Mem0

Mem0 is strongest as a general memory layer for LLM apps and agents. Its
official docs describe a universal memory layer, self-hosted open source, and
platform graph memory that links people, places, organizations, and concepts
across memories. Its paper reports LoCoMo gains and lower overhead versus
full-context baselines. [Unverified by this repo]

Do not argue that Shibahama is "more accurate than Mem0" on public conversation
benchmarks. The honest comparison today:

- Mem0 is the better default for teams wanting a broad app-memory product,
  hosted platform features, and ecosystem integrations.
- Shibahama is narrower: local-first Rust core, auditable mutation history,
  credence floors, human challenge/correct/pin flows, and replayable timelines.
- ContinuityBench is the current evidence that Shibahama's design helps when
  facts change and stale answers matter.

References:

- https://docs.mem0.ai/introduction
- https://docs.mem0.ai/platform/features/graph-memory
- https://arxiv.org/html/2504.19413v1

## Vs Zep / Graphiti

Zep and Graphiti are closest on temporal graph memory. Zep docs say its temporal
knowledge graph handles changing relationships and facts over time. The Graphiti
page describes temporal context graphs, invalidation of outdated facts, and
hybrid vector/full-text/graph retrieval; it also publishes LoCoMo and
LongMemEval numbers. [Unverified by this repo]

Do not frame Shibahama as obviously ahead of Zep. Frame the difference as build
shape:

- Zep/Graphiti is a production context graph system with published standard
  benchmark claims and hosted/service-oriented deployment.
- Shibahama is a smaller embeddable substrate with first-class audit, credence,
  and human review semantics exposed directly through core APIs and Tideline.
- Shibahama's best current proof is not standard recall; it is continuity under
  contradiction and supersession.

The current repo has no reproducible Zep/Graphiti run. The explicit not-run
anchor is `benchmarks/results/zep-graphiti-not-run.md`; do not claim a
Zep/Graphiti win until a real artifact replaces it.

References:

- https://help.getzep.com/graph-overview
- https://www.getzep.com/platform/graphiti/
- https://arxiv.org/abs/2501.13956

## Vs Letta

Letta is primarily an agent framework with explicit state and memory tools.
Its docs describe memory blocks attached to agents and archival memory as a
semantic database agents query on demand. That is an agent-operating model, not
just a retrieval backend.

The honest split:

- Letta is better when the developer wants a full stateful-agent runtime and
  memory tools as part of agent behavior.
- Shibahama is better when the developer wants a standalone memory engine that
  can be embedded behind a coding agent, framework, server, or custom runtime.
- Shibahama's distinguishing feature is not that agents can store facts; it is
  that changes to those facts remain replayable and inspectable.

References:

- https://docs.letta.com/guides/core-concepts/stateful-agents/
- https://docs.letta.com/guides/core-concepts/memory/archival-memory/

## Vs Engram

Engram is the closest published conceptual neighbor. Its arXiv abstract reports
a dual-process bi-temporal memory engine, lossless fast writes, asynchronous
fact extraction, contradiction resolution by invalidating rather than deleting,
hybrid retrieval, and LongMemEval-S results against full context. [Unverified by
this repo]

Treat Engram as a serious null hypothesis:

- Engram is stronger on published LongMemEval-S evidence today.
- Shibahama is stronger in this repo on developer-facing legibility: Rust core,
  public bindings, CLI/server parity, audit APIs, Tideline, and checked-in
  ContinuityBench artifacts with Mem0 and Engram exact-event anchors.
- Do not claim Shibahama beats Engram broadly. Claim only what the checked-in
  ContinuityBench table supports.

Reference:

- https://arxiv.org/abs/2606.09900

## Wording To Use

Use:

> Shibahama is a local-first memory substrate for coding agents that preserves
> history, exposes trust changes, and makes stale-answer behavior inspectable.

Avoid:

> Shibahama is the most accurate agent memory system.

Use:

> Checked-in LoCoMo and LongMemEval-S artifacts do not show standard benchmark
> superiority; the stronger proof today is continuity and epistemic-governance
> behavior.

Avoid:

> Shibahama beats Mem0/Zep/Letta/Engram.
