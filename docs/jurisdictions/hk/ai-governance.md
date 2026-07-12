<!-- SPDX-License-Identifier: Apache-2.0 -->

# Hong Kong AI governance and Solomon

Checked: 2026-07-12. This is a research and design note, not legal advice, a PDPO compliance assessment, or a
statement that a deployment meets PCPD guidance.

## Primary sources

- [PCPD: AI privacy protection resources](https://www.pcpd.org.hk/english/artificial_intelligence/index.html)
- [PCPD: Model Personal Data Protection Framework (2024)](https://www.pcpd.org.hk/english/resources_centre/publications/files/ai_protection_framework.pdf)
- [PCPD framework publication](https://www.pcpd.org.hk/english/news_events/media_statements/press_20240611.html)
- [PCPD: employee generative-AI guidance](https://www.pcpd.org.hk/english/news_events/newspaper/newspaper_20250514.html)

PCPD's 2024 Model Framework provides recommendations and best practices for organisations procuring, implementing,
and using AI, including generative AI, involving personal data. PCPD describes four areas: AI strategy/governance;
risk assessment/human oversight; model customisation plus system implementation/management; and stakeholder
communication/engagement. PCPD states that the Framework assists organisations with relevant PDPO requirements; it
does not make a product or deployment automatically compliant.

## Design mapping

| Framework area | Solomon contribution | Boundary |
| --- | --- | --- |
| Governance and strategy | Audit records, roles attached to verification events, and deployment configuration make parts of the currency workflow inspectable. | [Inference] The organisation establishes policy, ownership, governance committee, procurement criteria, and training. |
| Risk assessment and oversight | Preflight, stale states, contestability, and human affirmation expose uncertainty and route source review. | [Inference] The firm decides risk methodology, residual risk, oversight level, and escalation. |
| Model/system management | Boundary review, scoped retrieval, local-only routing, and evidence/version metadata support controlled context handling. | Solomon does not secure or validate a host model, vendor, training data, infrastructure, or output. |
| Communication and engagement | `why`, audit packs, and evidence references make source-currency reasons available for an integration. | Notices, stakeholder engagement, complaint handling, and required disclosures remain with the organisation. |

## Deployment evidence

1. AI purpose, data flow, data roles, vendor/subprocessor inventory, retention, and cross-border-access map.
2. Risk assessment, human-oversight design, testing, monitoring, and escalation record.
3. Boundary/preflight/verification/audit examples for the actual matter class.
4. Security, privacy, transparency, employee-use, incident, and remediation controls outside Solomon.

## Limits

Do not market Solomon as PCPD-approved, PDPO-compliant, secure, or suitable for a Hong Kong matter without current,
deployment-specific evidence and qualified review.
