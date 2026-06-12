# Why Shibahama

Shibahama is named after a classic rakugo story about a memory that is hidden,
preserved, and later reintroduced at the moment it can be understood correctly.

In the story, a man finds a wallet of gold on the beach at Shibahama. His wife
hides it and convinces him he dreamed the discovery. Years later, after his life
has changed, she reveals that the wallet was real. The point is not deletion.
The point is timing, context, and the difference between suppressing access to a
memory and destroying it.

That maps cleanly to the memory problem this project is trying to solve.

## The Design Philosophy

Shibahama does not treat memory as a warehouse where facts are simply written
and retrieved by similarity. It treats memory as state with history, trust,
access cost, and currency.

The name is meant to keep four design choices visible.

## Preserve History

The wallet is hidden, not burned. Shibahama follows the same rule for memory:
normal operations invalidate, compact, demote, and reconstruct, but they do not
delete source history.

This is the never-delete invariant. A stale fact can be closed with `valid_to`.
A cold memory can move out of default recall. A replacement can supersede an old
version. The event history remains available for audit and explanation.

## Accessibility Is Not Existence

In the story, the wallet still exists while the man cannot act on it. In
Shibahama, cold memories still exist while default recall does not surface them.

This is why the tier model matters:

- hot means cheap to surface;
- warm means normally searchable;
- cold means retained but explicit-cost retrieval.

Decay changes accessibility, not existence.

## Use Reveals Significance

The story only matters because the wallet changes meaning over time. Shibahama's
significance score is also time- and use-dependent. It is not a permanent label
assigned at ingest.

Access events, outcome signals, contradiction signals, and time decay decide
whether a memory becomes more or less load-bearing. That gives the system a
reason to keep certain memories visible even when they are not the newest or
most semantically similar facts.

## Recheck At The Moment Of Use

The reveal matters because it happens at the right moment. Shibahama applies the
same principle to stale but important memories: do not globally refresh
everything, and do not blindly trust old recall results.

When recall surfaces a significant memory that may be stale, reconstruction can
be explicitly requested. The system re-validates the memory, quarantines any
proposed update at lower credence, and only promotes it after corroboration.

That is the "Shibahama moment" in the engine: a memory returns from lower
accessibility, but it is checked against current reality before it is trusted.

## What The Name Should Prevent

The name is also a constraint. It should prevent two easy mistakes:

- deleting old memory and calling it decay;
- returning old memory unchanged and calling it context.

Shibahama is trying to sit between those failures. It keeps history intact while
making current, trusted, useful context cheaper to retrieve.
