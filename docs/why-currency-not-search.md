<!-- SPDX-License-Identifier: Apache-2.0 -->

# Why currency, not search

Search is necessary for firm knowledge, but it answers a narrower question: *what might be relevant?* A search
index ranks documents, clauses, and prior work using text and metadata. It can return an excellent memo that is
nevertheless unsafe to reuse because its authority moved, its conclusion was superseded, its verification is
overdue, or a lawyer has contested it.

Currency asks a different question: *may this position be used as current firm knowledge, and why?* Answering it
requires durable state rather than a better ranking model. Solomon records a knowledge item's provenance, valid and
ingestion time, dependency edges, verification events, supersession links, contest history, and audit trail. The
engine derives state from those records; it does not infer that a statement is wrong merely because it is old.

That distinction matters when a drafting or research host assembles context. Retrieval can identify a prior
position. Solomon's `preflight_context` can instead return the current position, omit stale material by default,
and include a compact reason when review is required. If an external authority changes, the dependency graph marks
affected positions `StalePendingReverification`; if a later internal view supersedes an earlier view, both records
remain available for reconstruction while only the current one is eligible for normal reuse.

This is not a claim that Solomon replaces search. A DMS, knowledge base, or legal assistant still provides the
documents, permissions, and user workflow. Solomon adds a narrow control plane between that corpus and model-bound
context: deterministic currency evaluation, impact analysis, and evidence export. It is also not a citator or an
automatic authority monitor. A firm must supply or confirm the change events that drive re-verification.

The practical result is a different review conversation. Instead of “the system found a memo,” a curator can ask:
which source supports this position, what changed upstream, when was it last verified, which downstream materials
are affected, and what did the system expose to a host? Solomon preserves the evidence needed to answer those
questions and leaves legal judgement with the lawyer.
