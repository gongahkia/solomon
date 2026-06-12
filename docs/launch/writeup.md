# Shibahama Launch Writeup

Long-lived agents do not only need more memory. They need memory with currency,
trust, and history.

The common failure is familiar: an agent remembers a related fact but not whether
the fact was superseded, rejected, low-trust, or only useful in a previous phase
of the project. That is how stale file paths get cited, rejected designs get
suggested again, and model-authored notes slowly become indistinguishable from
source-backed decisions.

Shibahama is an embeddable memory engine for that failure mode. It treats memory
as a durable stream of claims instead of a bag of text chunks.

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
- recency and optional graph signals;
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

The local harness can run Shibahama and a warehouse baseline today. LoCoMo and
LongMemEval comparisons still require external dataset exports. External-system
adapters should not be claimed until they are backed by reproducible successful
runs.

The current claim is narrower: Shibahama has the mechanics needed for
currency-aware, provenance-aware, reconstructive memory, and the repo contains
local tests and demos for those mechanics.
