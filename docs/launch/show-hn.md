# Show HN: Shibahama - an embeddable memory engine that remembers why you said no

Shibahama is an in-process memory engine for long-lived agents. It is built for
the failure mode where an agent remembers facts but forgets the history around
them: why a decision was rejected, when a file moved, which source superseded an
older claim, and whether a memory is still safe to use.

The core is a small Rust crate with Python and Node bindings. It stores memories
with provenance, valid-time and ingestion-time timestamps, credence tiers, access
history, and an append-only event log. Recall combines vector search with
significance, recency, graph context, and currency checks. The default behavior
is conservative: stale-but-important memories are flagged for re-validation
rather than silently rewritten, and low-credence memories cannot outrank trusted
ones just because they were retrieved often.

The hook I would lead with: Shibahama remembers why you said no. If a coding
agent was told not to add a global singleton store, that rejection can become a
high-significance, high-credence memory. Future recall can surface the rejection
instead of re-suggesting the same bad approach.

There is also a visual debugger, Tideline, which replays the event stream:
promotions, demotions, invalidations, reconstruction moments, poisoning
quarantine, bi-temporal state, graph changes, and shareable clips.

What is in the repo now:

- Rust core with `write`, `recall`, `reinforce`, `why`, and `timeline`.
- Python and Node bindings with smoke-tested parity.
- Optional HTTP server mode with namespace isolation and metadata-only logging.
- CurrencyBench, a small benchmark for fact changes and stale-answer behavior.
- A runnable coding-agent demo and Tideline recording source.

What I would like feedback on:

- Whether the significance/reconstruction model matches agent-memory failures
  you have seen in real projects.
- Whether the API is small enough to embed directly in agent frameworks.
- Which benchmark or integration would make the comparison against existing
  memory systems more credible.
