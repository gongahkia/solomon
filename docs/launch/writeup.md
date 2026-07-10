# Shibahama Launch Writeup

Long-lived agents do not only need more memory. They need memory with currency,
trust, human contestability, and inspectable history.

The common failure is familiar: an agent remembers a related fact but not whether
the fact was superseded, rejected, low-trust, or only useful in a previous phase
of the project. That is how stale file paths get cited, rejected designs get
suggested again, and model-authored notes slowly become indistinguishable from
source-backed decisions.

Shibahama is an embeddable memory engine for that failure mode. It treats memory
as a durable stream of claims instead of a bag of text chunks. Its narrow
positioning is append-only, never-delete source/event memory with credence
floors, explicit human signal verbs, and a debugger that shows why
reconstruction or consolidation happened.

## What It Stores

Each memory carries:

- content and kind;
- provenance;
- valid-time and ingestion-time bounds;
- credence tier;
- accessibility tier;
- significance score;
- access history;
- append-only event history.

Invalidation closes a valid-time interval. It does not delete the row. That
means a caller can ask both "what is current?" and "what did the agent believe at
that point in the session?"

## What Recall Does

Recall starts with vector search, then applies deterministic policy:

- valid-now filtering by default;
- significance-aware ranking;
- recency and graph-expansion signals;
- credence floors;
- cold-tier opt-in;
- read-safety sanitization;
- stale-but-load-bearing flags.

The important part is not that every memory gets a score. It is that the score is
explainable. `why(memory_id)` returns the significance breakdown, provenance,
currency state, tier state, and audit trail.

## Reconstruction Instead Of Silent Rewrite

When a significant memory looks stale, Shibahama does not mutate memory as a side
effect of a plain read. Re-validation is explicit and budgeted. Proposed updates
can enter quarantine at lower credence, then be promoted only after human
confirmation, a high-credence source, or a second consistent observation.

This is the core design stance: old memories should be revisited, not overwritten
without a trace.

## Debugging With Tideline

Tideline is the visual debugger for the event stream. It shows tier movement,
why-traces, poisoning quarantine, bi-temporal state, graph edges, session diffs,
and exportable replay clips. The goal is to make memory behavior inspectable
enough that a developer can debug an agent run without guessing what context was
silently assembled.

## What Is Ready

The repository includes:

- Rust core;
- Python and Node bindings;
- optional server mode;
- deterministic local benchmarks;
- CurrencyBench dataset/generator;
- coding-agent demo;
- Tideline debugger;
- docs for architecture, concepts, security, performance, and ADRs.

## What Still Needs External Proof

The local harness can run Shibahama, warehouse, full-context, and Mem0 OSS
exact-event baselines today. LoCoMo and LongMemEval loaders accept official
dataset exports, and the checked-in Phase C artifacts report those standard
benchmarks without claiming broad superiority.

Engram is now the closest published comparison for bi-temporal, non-destructive
agent memory. Any launch claim about supersession, point-in-time recall, or
token-efficient LongMemEval-S retrieval needs either a direct reproducible
comparison or a narrower claim that avoids implying superiority.

The current claim is narrower: Shibahama has the mechanics needed for
currency-aware, provenance-aware, human-contestable reconstructive memory, and
the repo contains local tests and demos for those mechanics.
