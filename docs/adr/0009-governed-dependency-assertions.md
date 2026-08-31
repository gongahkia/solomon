<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0009: Governed Explicit Dependency Assertions

## Status

Accepted for the bounded implementation described by the Governed Dependency Assertion Proof Protocol.

## Context

Solomon’s deterministic extractor has reached its approved conservative boundary. A citation parser can produce
review candidates but cannot establish that an internal position actually depends on an authority. Further parser
language would increase unverified semantic interpretation rather than give a curator a durable way to state and
review the relationship they actually intend.

The repository already has a persisted `DependencySuggestion` lifecycle, document-version provenance, scoped
knowledge, a bi-temporal edge store, and an append-only audit journal. Creating a parallel assertion subsystem would
split review, graph, authorization, and audit behavior.

## Decision

Use the existing durable dependency-suggestion lifecycle as the governed assertion record. Add explicit human and
trusted-upstream origins, bounded directional assertion types, immutable source-version evidence, canonical
registered targets, scope validation, idempotency, revision/re-verification links, withdrawal, and review provenance.
Only an authorized review decision creates a `human_confirmed` edge that points back to the assertion ID.

Quote evidence must reconstruct exactly from one stored document version; commentary is explicit semantic commentary
rather than synthetic quote evidence. Default separation of duties denies creator self-confirmation. MCP remains a
read-only scoped provenance surface. Parser output and LLM output retain their existing candidate-only behavior.

## Consequences

Curators can express dependencies the parser should not infer while preserving the same graph and currency controls.
The product can show evidence, actor, decision, revision, and edge linkage in an audit pack. It deliberately does not
prove legal accuracy, make source/graph stores cross-database atomic, or replace external authority registration and
operational governance.
