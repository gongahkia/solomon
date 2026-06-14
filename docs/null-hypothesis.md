# Null Hypothesis

Shibahama should be evaluated against the possibility that it is unnecessary for
many memory workloads.

The null hypothesis is simple: for one-shot question answering over mostly
static history, flat retrieval, a well-tuned RAG pipeline, or a long-context
model may match or beat a reconstructive memory system. If the whole useful
history fits in context, or if the question only asks for a fact that appears
verbatim in past text, Shibahama's extra state machinery may be cost without
accuracy benefit.

## Evidence We Accept

LoCoMo remains useful as a long-conversation memory benchmark, but it is not a
complete test of mutable, operational memory. The LoCoMo paper frames the task as
very long-term conversational memory over multi-session conversations averaging
about 9K tokens, with QA, summarization, and dialogue-generation tasks:
https://arxiv.org/abs/2402.17753.

LongMemEval broadened the evaluation target to information extraction,
multi-session reasoning, temporal reasoning, knowledge updates, and abstention.
It also reports substantial accuracy drops for commercial assistants and
long-context models under sustained interaction:
https://arxiv.org/abs/2410.10813.

Engram is the closest direct comparison for Shibahama's current thesis. It
claims a bi-temporal memory engine with lossless episodes, non-destructive
supersession, provenance chains, hybrid dense/lexical/graph/recency retrieval,
and a reproducible LongMemEval-S run scoring 83.6% from about 9.6K retrieved
tokens versus 73.2% for full context at about 79K tokens. Shibahama should not
claim bi-temporal invalidation or never-delete history as sufficient
differentiators unless it also proves a better stale-rate, auditability, or
token-cost result on a matching continuity slice:
https://arxiv.org/abs/2606.09900.

Recent 2026 work makes the threat sharper. MemTier reports that LoCoMo scores can
be insensitive to memory architecture when conversations are available in
context, and argues LongMemEval-S is more discriminating because it requires
storage and retrieval across 53 sessions:
https://arxiv.org/html/2605.03675v2.

MemMachine reports a LongMemEval-S ablation where retrieval-stage optimizations
outweigh ingestion-stage changes. That is a direct warning that better search,
formatting, and answer-model choices can dominate architectural novelty on
standard QA metrics:
https://arxiv.org/html/2604.04853v1.

Memora / FAMA targets the failure mode Shibahama is actually built for:
non-stationary memory where information is updated, corrected, or withdrawn. It
penalizes reliance on obsolete or invalidated memory and reports persistent
failures across LLMs and memory agents:
https://arxiv.org/html/2604.20006v1.

LongMemEval-V2 reframes agent memory as environment experience: memory should
help agents become experienced operators of specialized environments, not merely
answer isolated questions over chat logs:
https://arxiv.org/abs/2605.12493.

## What Shibahama Should Claim

The honest claim is not "Shibahama beats flat retrieval everywhere."

The claim is narrower:

- Shibahama should win when facts recur and change over time.
- Shibahama should reduce stale-answer rate by making validity, supersession,
  corroboration, and human challenge state explicit.
- Shibahama should reduce retrieval token cost on continuity tasks by keeping
  old context cold while preserving auditability.
- Shibahama should make failures legible through `why()` and Tideline, even when
  a simpler baseline wins raw QA accuracy.

That makes CurrencyBench, forgetting-aware mutation tasks, and long-running
coding-agent continuity tasks the home turf. LoCoMo and LongMemEval are still
important, but they must be reported with flat retrieval and long-context
baselines, including cases where those baselines win.

## Benchmark Rules

Every public benchmark claim should include:

- a flat retrieval or keyword baseline;
- the closest reproducible bi-temporal/non-destructive comparison, currently
  Engram, when that feature family is part of the claim;
- retrieval token cost;
- stale-answer rate when the dataset contains changing facts;
- Shibahama ablations for significance, reconstruction/supersession, and graph
  expansion when those features are part of the claim;
- committed raw result artifacts, not just prose summaries.

Do not cite the local coding-agent benchmark as passing until a real checked-in
result artifact exists. Do not claim LoCoMo or LongMemEval superiority without
running their official exports and publishing the corresponding artifacts.
