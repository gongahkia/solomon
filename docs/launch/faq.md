# Launch FAQ

## Is this just a cache?

No. A cache usually optimizes repeated lookup of values that are still assumed
valid. Shibahama stores memory as historical claims with provenance, valid-time,
ingestion-time, credence, access history, and an append-only event log.

The key behavior is currency-aware recall. A memory can be useful and still
possibly stale. Shibahama can flag that state, preserve the old row, and plan or
apply re-validation without silently overwriting history.

## What is the null hypothesis?

The null hypothesis is that ordinary vector retrieval plus better prompting is
enough for long-lived agent memory. Shibahama should only matter when the task
needs one or more of:

- remembering rejected decisions;
- distinguishing current facts from superseded facts;
- preserving why a memory was trusted or distrusted;
- auditing how a memory changed over time;
- preventing low-credence retrieved content from outranking trusted content.

CurrencyBench and the coding-agent demo are designed around that hypothesis:
plain retrieval can find related text, but it should fail when stale related text
is actively dangerous.

## How is Shibahama different from other agent-memory systems?

The defensible difference is not "it uses memory signals." Current systems
already claim multi-signal and temporal retrieval. Shibahama's narrower claim is
that never-delete history, credence floors, append-only human signals
(`challenge`, `affirm`, `correct`, `pin`), and Tideline-visible
reconstruction/consolidation make memory behavior easier to audit and contest.

Engram is the closest published comparison for bi-temporal, non-destructive
memory. Shibahama should not imply superiority there without checked-in
LongMemEval-S, LoCoMo, or continuity-task artifacts.

## Why not put all of this in the prompt?

Prompting can ask a model to be careful, but it cannot by itself enforce durable
history, valid-time filtering, credence floors, append-only invalidation, or
budgeted re-validation. Shibahama moves those mechanics into a deterministic
memory layer so the model sees a smaller, safer context.

## How is significance different from recency?

Recency says a memory is recent. Significance says it has repeatedly mattered.
The default significance score combines decay, access reinforcement, caller
outcomes, contradiction penalties, and optional graph centrality. A recent but
ignored fact need not stay hot; an older rejection can stay prominent if it keeps
preventing bad work.

## How does Shibahama avoid memory poisoning?

Shibahama does not treat all retrieved memories as equal. It separates credence
from usefulness, quarantines lower-trust sources by default, preserves provenance,
and prevents low-credence memories from outranking authoritative memories on
otherwise identical recall signals.

It also offers read-safety sanitization hooks for instruction-like stored
content. This reduces prompt-injection risk from memory recall, but it is not a
complete security boundary by itself.

## What is not guaranteed?

Shibahama does not prove that a memory is true. It tracks source, trust tier,
currency, and usage signals so callers can make better decisions. External source
verification, tenant isolation, encryption operations, and model-output policy
remain the responsibility of the embedding application.

## Why the name?

The name comes from the rakugo story "Shibahama", where the important question is
not just what happened, but what should be remembered, when it should be trusted,
and how a person changes after being forced to revisit a memory. That maps well
to an agent memory system that treats use, trust, and reconstruction as first
class.
