<!-- SPDX-License-Identifier: Apache-2.0 -->

# EU AI Act: legal decision support

Checked: 2026-07-12. This is a research note for UK firms whose AI-system output is used in the Union. It is not legal
advice, a classification decision, or a statement that Solomon is an AI system or falls inside/outside the AI Act.

## Primary source and correction

- [Regulation (EU) 2024/1689 (AI Act), current EUR-Lex text](https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng)

The task's reference to Article 52 is not the adopted Act's transparency provision: Article 52 is a procedure.
Article 50 contains the adopted Act's transparency obligations. This note therefore reviews Article 2, Article 6,
Annex III point 8, Article 50, and Article 113 in the current text.

## Scope and dates

Article 2 covers providers/deployers established outside the Union where an AI system's output is used in the Union.
Article 113 provides that the Regulation generally applies from 2 August 2026; Article 6(1) and corresponding
obligations apply from 2 August 2027. Check the current text and any implementing/guidance material before deployment,
especially after those dates.

## Classification: legal decision support

Article 6(2) classifies Annex III systems as high-risk, subject to Article 6(3). Annex III point 8(a) identifies AI
systems intended for use by, or on behalf of, a judicial authority to assist research/interpretation of facts and law
or application of law to facts; it also covers similar alternative-dispute-resolution use. The Annex III classification
is tied to intended purpose and use context, not a product label such as “legal research”.

Article 6(3) provides a narrow non-high-risk route for Annex III systems that do not pose significant risk to health,
safety, or fundamental rights, including narrow procedural tasks, improving a previously completed human activity,
pattern/deviation detection that does not replace or influence a human assessment without proper review, and preparatory
tasks. A provider taking that route must document the assessment and register as Article 49(2) requires. Profiling of
natural persons remains high-risk under Article 6(3).

For a private law firm, this note cannot determine whether a system is within Annex III point 8. A workflow used by a
judicial authority, on its behalf, or in similar ADR is materially different from firm-internal research. Obtain
deployment-specific EU advice before classifying a system, assigning provider/deployer roles, or relying on Article 6(3).

## Solomon mapping and limits

| Concern | Solomon contribution | Boundary |
| --- | --- | --- |
| Intended-purpose record | Configuration, audit packs, source/version metadata, and event history preserve evidence of how a currency decision was made. | [Inference] This can assist a classification record; it does not define intended purpose or determine an operator role. |
| Human review | Verification, affirmation, contest, and stale states record human intervention in source currency. | Solomon does not make the final decision human-driven or establish legally sufficient human oversight. |
| Traceability | `why`, impact paths, hashes, and deterministic state transitions support reconstruction of a context decision. | Traceability of Solomon context is not full AI-Act technical documentation, logging, or conformity evidence for a host AI system. |
| Transparency | An integration can disclose Solomon's source-currency status and evidence links. | The provider/deployer decides whether Article 50 or other transparency duties apply and supplies required notices. |

## Review evidence

1. Actual intended purpose, users, affected persons, operator roles, and territories where outputs are used.
2. Whether any workflow is for a judicial authority, its delegate, or similar ADR, and whether it influences a natural-person decision.
3. Article 6 / Annex III classification analysis, including a documented Article 6(3) assessment if relied upon.
4. Model, host application, data, human-oversight, risk-management, technical-documentation, logging, and transparency evidence outside Solomon.
5. Applicable-date analysis and subsequent Commission guidance, delegated acts, and national implementation.

## Limits

Do not represent Solomon as EU AI Act-compliant, non-high-risk, low-risk, transparent, or suitable for EU legal
decision support without qualified, deployment-specific assessment.
