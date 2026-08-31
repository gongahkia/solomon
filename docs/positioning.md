<!-- SPDX-License-Identifier: Apache-2.0 -->

# Positioning

## Tagline

Selected: **A self-hosted provenance and change-impact control plane for high-stakes AI systems, initially applied to internal legal knowledge.**

Alternatives considered:

1. Currency infrastructure for verified legal knowledge.
2. Know what is current before you reuse it.
3. Verified context for legal work.

The selected line names the deployment model, control-plane role, high-stakes scope, and initial vertical without
claiming that Solomon decides legal correctness. Use it verbatim in product metadata.

Solomon is the layer that tells a host application whether an internal legal position is still usable, what it
depends on, and what evidence requires re-verification. It is not a citator, general document-management system,
legal research database, drafting copilot, agent-memory system, or legal-advice product. **Flag, do not adjudicate.**

For its documented deployment profiles, Solomon durably records the governed multi-stage operations behind that
answer and can inspect or safely reconcile defined incomplete projections after interruption. This is a bounded
recovery claim, not a distributed transaction across source SQLite, PostgreSQL, and the audit journal.

## The wedge: currency, not retrieval

A retrieval result answers “what material might help?” Solomon additionally records the lifecycle of a position:
valid time, ingestion time, provenance, dependency edges, supersession, verification, contestability, and audit
events. When an authority or upstream position changes, Solomon propagates a `StalePendingReverification` state
through dependents. A host can then withhold stale text by default and present the reason for review.

This makes Solomon complementary to a DMS, knowledge search product, research service, or legal assistant. Those
systems may supply documents or draft work; Solomon supplies a deterministic currency gate and its evidence. A human
decides whether an affected position remains legally correct.

## Market boundary

| Product | Publicly described focus | Solomon distinction |
| --- | --- | --- |
| [Harvey](https://www.harvey.ai/platform) | Legal AI workspace for research, drafting, review, workflows, and knowledge. | Solomon can provide a host-neutral currency and dependency control plane before a host reuses internal content. |
| [iManage Insight+](https://imanage.com/imanage-products/knowledge-search-management/insightplus/) | Contextual discovery, curated collections, and governed DMS knowledge. | Solomon does not replace DMS retrieval or permissions; it stores the lifecycle and re-verification evidence of internal positions. |
| [CoCounsel Legal](https://legal.thomsonreuters.com/en/products/cocounsel-legal/corp) | Legal research, analysis, drafting, and document work grounded in Thomson Reuters content. | Solomon is not a legal research or drafting assistant; its output is current-context metadata for any compatible host. |
| [Spellbook](https://www.spellbook.legal/) | Contract-drafting and review workflows. | Solomon tracks whether internal clauses or positions used in those workflows need review after a dependency moves. |
| [Legora](https://legora.com/about) | Collaborative AI workspace for legal work. | Solomon exposes deterministic, auditable currency primitives rather than an end-user AI workspace. |
| [Paxton](https://help.paxton.ai/help/ai-assistant/using-the-ai-assistant) | AI-assisted legal drafting, research, and document analysis. | Solomon assesses the currency of firm knowledge supplied to a host; it does not replace the host's task execution. |

The table is a scope comparison from public vendor materials retrieved on 2026-07-12, not a feature-parity,
security, price, or legal-compliance assessment. Product capabilities change; verify current vendor documentation
before procurement or integration decisions.

## Intended deployment

Solomon runs as an MCP server, FastAPI service, or CLI. An MCP host calls deterministic tools such as
`preflight_context`, `why`, `impact`, and `audit_pack`; the host retains responsibility for prompting, drafting,
and human review. The curator console is a first-class review surface for knowledge teams to manage dependencies,
verification, and audit evidence.

## Non-claims

- Solomon does not decide the law or certify that a position is correct.
- Solomon does not monitor every external authority or replace a citator.
- Solomon does not prove a host's model, deployment, or retention controls.
- A currency result is evidence for human review, not a substitute for professional judgement.

For the conceptual distinction, see [`why-currency-not-search.md`](./why-currency-not-search.md). For operational
limits, see [`known-limitations.md`](./known-limitations.md).
