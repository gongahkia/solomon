# Concepts

This document explains the core Shibahama concepts as they exist in the current
implementation. For module boundaries and request flows, see
`docs/architecture.md`.

## Memory Item

A memory item is the durable unit Shibahama writes, recalls, explains, and
invalidates. It is not just text. Each item carries:

- a stable UUIDv7 memory id;
- content;
- a semantic kind, currently fact or instruction;
- provenance;
- valid-time and ingestion-time timestamps;
- tier;
- credence;
- significance;
- a credence floor;
- optional embedding metadata;
- access events.

Recall candidates expose provenance, tier, currency, and scoring details so
callers do not receive bare text without context.

## Provenance

Provenance records where a memory came from and who ingested it. The current
source kinds are:

- `User`;
- `Agent`;
- `File`;
- `Web`;
- `Tool`.

Ingestion uses source kind to assign conservative default trust. A user-supplied
memory starts more trusted than a web import or model-authored observation. The
caller can still provide explicit credence when it has stronger domain knowledge.

## Bi-Temporality

Shibahama tracks two different time questions:

- When was this fact claimed to be true in the represented world?
- When did Shibahama learn it?

The first question uses `valid_from` and optional `valid_to`. The second uses
`ingested_at`.

This distinction matters when facts are learned late or corrected later. A file
may have moved last month, while Shibahama only learned that today. Timeline
queries need to preserve both truths.

Default recall asks for facts believed now. `timeline(query, as_of)` asks what
Shibahama had ingested and believed at a specific instant, without recording a
new surfaced-access event.

## Currency

Currency is the validity state of a memory at a query time:

- `Current`: valid at the query instant.
- `NotYetValid`: the memory starts after the query instant.
- `Invalidated`: the memory's valid interval has been closed.

Default recall filters to current, believed facts. Invalidated memories remain
in storage and event history, but they do not appear in normal recall.

## Never Delete

Shibahama's core safety invariant is that memory history is not destroyed by
normal memory operations.

Invalidation closes a valid-time interval. Compaction can move cold content to a
compressed payload. Tier enforcement can demote hot items. None of these erase
the source event, provenance, or historical row needed to explain what happened.

This is why the event log is the source of truth and materialized state is only
the current view.

## Significance

Significance is an explainable usefulness score. It answers: "How much has this
memory mattered in practice?"

The default scorer combines:

- the item's base score after time decay;
- diminishing-returns reinforcement from access count;
- outcome weights from surfaced, useful, cited, ignored, or contradicted access
  events;
- contradiction penalties;
- optional graph centrality.

The function is deterministic and configurable. It is deliberately not learned
in the current implementation, because users need to inspect why a memory is
hot, stale, demoted, or still protected.

`why(memory_id)` returns the significance breakdown used by the current engine.

## Access Outcomes

Access events record how recall results were used:

- `Surfaced`: recall returned the memory.
- `LedSomewhere`: the memory helped the caller make progress.
- `Cited`: the memory was explicitly used in output or downstream work.
- `Ignored`: the caller surfaced but did not use it.
- `Contradicted`: the access exposed a conflict.

Plain recall records `Surfaced` for returned candidates. Stronger usage signals
come from explicit reinforcement calls.

## Tiers

Tier is access cost, not trust.

- `Hot`: highly significant and cheap to surface.
- `Warm`: normally searchable.
- `Cold`: retained but excluded from default recall unless the caller opts in.

Significance can promote or demote items lazily. Access and useful outcomes move
items hotter. Decay and weak outcomes can move items colder.

Cold does not mean deleted. A cold item is still retained for explicit recall,
timeline reconstruction, and explanation.

## Credence

Credence is trust, not popularity. The current tiers are:

- `FirmAuthoritative`: explicit user instruction, pinned project decision, or
  caller-marked authority.
- `VerifiedSource`: observed from a source that can be re-read or verified.
- `ModelInferred`: inferred by an agent or model.
- `Unverified`: web-imported, reconstructed, or otherwise unconfirmed content.

Credence prevents usage from laundering weak provenance into authority. A
frequently accessed unverified memory may become significant, but it should not
outrank a conflicting authoritative memory just because it is semantically close
to the query.

Recall ranks by credence before weighted recall score.

## Credence Floor

The credence floor is the coldest tier a memory may occupy after demotion. It is
how Shibahama protects load-bearing memories from fading into practical
invisibility.

A rare but explicit "do not use this approach again" decision may need to remain
warm even if it is not frequently retrieved. That is separate from significance:
the memory may not be popular, but its trust and safety value still matter.

## Facts And Instructions

Stored facts and stored instructions are separated by `MemoryKind`.

Default recall returns facts. Instructions require explicit opt-in. This keeps
stored directives from being mixed into ordinary factual context by accident and
supports the read-safety posture that treats memory as untrusted input.

Read-time safety filters also neutralize stored content that looks like an LLM
role directive before returning it to callers.

## Reconstruction

Reconstruction is the process of checking and updating a significant memory that
may be stale. It is designed around explicit control, not background mutation.

The trigger is a recall candidate flagged as load-bearing and possibly stale:
high significance, old enough, and lacking a recent validation-like signal.

The gate decides whether reconstruction may run:

- ordinary reads use `PlainRead`, where reconstruction must not run;
- callers that want re-validation use `ExplicitRevalidation`.

This matters because a normal `recall` should not unexpectedly mutate memory
state.

## Quarantine And Corroboration

Reconstructed proposals enter cautiously. A proposed update is stored at lower
credence, kept cold, and tagged as quarantined. It does not become authoritative
just because the system generated it.

A quarantined proposal can be promoted when there is enough corroboration:

- human confirmation;
- a high-credence source;
- enough independent consistent observations.

When a proposal is accepted, Shibahama invalidates the superseded memory and
writes the replacement as a separate memory. It does not overwrite the original.

## Graph

The graph substrate stores typed entities and directed relations using the same
bi-temporal model as memory items. Relations can support recall expansion,
contradiction detection, supersession links, scoped subgraphs, and graph
centrality input for significance.

Graph expansion is optional at recall time through a related-memory provider.
The default vector recall path remains bounded to vector candidate ids unless
the caller supplies graph-related ids.

## Error Posture

Writes fail closed. If Shibahama cannot durably append the event and update
materialized state consistently, the write returns an error rather than
pretending memory was persisted.

The public Rust API exposes stable error categories and recovery guidance for
storage, vector, recall, invalid request, and async task failures. Binding and
server surfaces should preserve those structured codes instead of reducing them
to opaque strings.

## How The Concepts Fit

The concepts are separate axes:

- significance answers how useful a memory has been;
- credence answers how much the system should trust it;
- tier answers how cheap it is to retrieve by default;
- currency answers whether it is valid at the query time;
- provenance answers where it came from;
- reconstruction answers how stale important memories are checked without
  overwriting history.

Keeping those axes separate is the main design choice. It lets Shibahama
remember that something mattered, remember why it was trusted or distrusted, and
still preserve enough history to explain later changes.
