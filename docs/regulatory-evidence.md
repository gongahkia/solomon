<!-- SPDX-License-Identifier: Apache-2.0 -->

# Regulatory Evidence

Solomon's audit chain is not only a privilege-defense artifact. It is also a regulator-ready evidence
structure for explaining what the system did, why it did it, which source material it used, which human
or system actor was accountable, and whether the answer remained current at the time it was produced.

This document describes the evidence model. It does not certify compliance, classify a deployment as high
risk or low risk, or decide whether a legal position is correct. Solomon flags currency, provenance,
credence, and contestability signals so a qualified reviewer can make those judgments.

## Evidence Model

Every answer should be explainable from these artifacts:

| Regulator question | Solomon evidence |
|---|---|
| What did the system do? | `answer_workflow` audit transaction, endpoint decision metadata, recalled item ids, and model-call metadata. |
| Why did it do that? | Deterministic primitive plan from `/plans/execute` or the answer workflow's primitive recall plan, including validated step names, argument hashes, result hashes, and summaries. |
| On what basis? | `KnowledgeItem` provenance, source kind, source reference, matter/client scope, parsed legal references, dependency edges, and currency state. |
| Was the basis still current? | `evaluate_currency`, `impact_query`, verification records, authority-change events, supersession links, stale reasons, and timeline/as-of reconstruction. |
| Who was accountable? | `verified_by`, source-derived credence tier, tenant principal metadata, partner affirmations, pin metadata, and audit actor ids where available. |
| Could a human challenge it? | `contest` history, quarantined proposed corrections, `affirm` decisions, `pin` decisions, and never-delete supersession records. |
| What crossed the model boundary? | Solomon boundary review and pseudonymization metadata, route decision, prompt hashes, mapping counts, and volatile mapping flush evidence. |

The audit journal remains metadata-only: it records ids, hashes, states, route decisions, and timestamps,
not privileged prompt text or stored legal content.

## EU AI Act Article 13

The EU AI Act is Regulation (EU) 2024/1689. Article 113 provides a general application date of 2 August
2026 with staged exceptions, and the European Commission's AI Act page identifies August 2026 for the
Act's transparency rules. Article 13 requires high-risk AI systems to be transparent enough for deployers
to interpret system output and use the system appropriately, with instructions that are concise, complete,
correct, clear, relevant, accessible, and comprehensible.

Solomon supports that transparency requirement through reproducible operational evidence:

- The answer path records a deterministic primitive call-plan before model text is assembled. The plan is
  human-readable, has a stable plan hash, and can be re-executed against the same store state.
- The LLM does not decide currency, supersession, timeline state, or verification status. Those outcomes
  are produced by typed deterministic primitives.
- The `why` path reconstructs the plan and evidence chain behind an answer, including recalled items,
  currency state, dependencies, verification status, boundary metadata, and model-call metadata.
- The contestability path records challenges and keeps proposed corrections quarantined until a
  `FirmAuthoritative` actor affirms them.

This is an explanation structure for Solomon's own behavior. It is not a substitute for the provider's
formal instructions for use, conformity assessment, legal-risk classification, or deployer obligations.

## Multi-Jurisdiction Mapping

Solomon's evidence model is jurisdiction-agnostic. The same record structure can support different
regulatory, professional, and client-review questions while the substantive rules remain jurisdiction-
specific.

| Framework | Evidence alignment |
|---|---|
| EU AI Act | Article 13-style output interpretation, instructions-for-use support, human oversight evidence, deployer accountability, and Article 27-style impact review inputs where applicable. |
| NIST AI RMF 1.0 | Govern: roles, policies, boundary controls, tenant scopes, and audit records. Map: intended use, source provenance, dependencies, and matter/client context. Measure: currency status, stale-surface benchmarks, boundary-fidelity tests, and evaluation artifacts. Manage: contest, affirm, pin, supersede, retire, and authority-change propagation. |
| ISO/IEC 42001:2023 | Evidence for an AI management system: policies and objectives, lifecycle processes, risk handling, monitoring, review, and continual improvement records around responsible AI use. |
| Boundary jurisdiction packs | Solomon uses 18-jurisdiction statute framing for boundary review. The evidence chain records which context was reviewed and sanitized, but each jurisdiction's privilege, confidentiality, privacy, and professional-responsibility analysis remains outside Solomon's adjudication scope. |

The important distinction is between evidence structure and legal conclusion. Solomon can show that a
given answer came from a reproducible plan, current or stale source material, a known credence tier, and a
visible contest history. It cannot decide whether that record satisfies a regulator, bar authority,
court, client, or internal risk committee.

## Review Packet

A regulator-ready review packet should include:

- the answer response with its primitive plan summary;
- the `why` response for the answer or recalled item;
- the relevant `KnowledgeItem` provenance and verification records;
- dependency graph edges and `impact_query` output for any changed authority;
- contest, affirm, pin, supersession, and retire events;
- boundary review and pseudonymization metadata;
- audit-pack manifest and hash-chain verification output;
- known limitations and deployment-specific instructions for use.

If a requested packet requires legal content, client identities, or privileged prompt text, export it from
the authoritative store under the firm's own review process. Do not infer that content from the audit
journal, because the journal deliberately stores metadata and hashes only.

## Sources

- [Regulation (EU) 2024/1689, Article 13 and Article 113](https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng)
- [European Commission, AI Act overview](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)
- [NIST AI Risk Management Framework 1.0](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Playbook](https://airc.nist.gov/airmf-resources/playbook/)
- [ISO/IEC 42001:2023 overview](https://www.iso.org/standard/42001)
