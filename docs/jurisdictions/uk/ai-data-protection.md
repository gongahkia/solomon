<!-- SPDX-License-Identifier: Apache-2.0 -->

# United Kingdom: AI, legal-services supervision, and data protection

Checked: 2026-07-12. This is a research and design note, not legal advice, a compliance determination, or a
substitute for a firm's SRA, UK GDPR, DPA 2018, contract, or client-matter analysis.

## Primary sources

- [SRA: Effective supervision guidance](https://www.sra.org.uk/solicitors/guidance/effective-supervision-guidance/)
- [ICO: Guidance on AI and data protection](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/guidance-on-ai-and-data-protection/)
- [ICO: lawfulness in AI](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/guidance-on-ai-and-data-protection/how-do-we-ensure-lawfulness-in-ai/)
- [ICO: security and data minimisation in AI](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/guidance-on-ai-and-data-protection/how-should-we-assess-security-and-data-minimisation-in-ai/)

The SRA's current effective-supervision guidance says AI-assisted or AI-generated legal-service outputs need
appropriate human review, scrutiny, and professional judgement. It says an authorised individual must retain ultimate
responsibility for legal services delivered with AI assistance. The guidance also describes supervision as risk-based;
the required level and form depend on the work, risk, competence, and delivery context.

The ICO's AI guidance describes its interpretation of data-protection law and recommended good practice; it is not a
statutory code. It addresses lawfulness, fairness, transparency, purpose limitation, data minimisation, accuracy,
storage limitation, security, accountability, and individual rights. The ICO says a controller must choose the lawful
basis for AI processing and distinguish purposes between development and deployment. It also says AI processing can
increase security risk and requires risk-appropriate security measures.

## Design mapping

| Concern | Solomon contribution | Boundary |
| --- | --- | --- |
| Authorised human review | `verify`, `affirm`, `contest`, and `pin` events retain actor, time, evidence, and state. | [Inference] This can support a review record; it does not perform the review or transfer professional responsibility. |
| Risk-based supervision | Preflight, `why`, dependency paths, stale states, and audit packs expose source status and downstream impact. | [Inference] The firm decides engagement risk, sampling, supervision frequency, escalation, and who is competent to supervise. |
| Purpose limitation and minimisation | Scoped retrieval, boundary checks, local-only routing, and metadata-oriented audit data limit unnecessary context flow. | [Inference] The firm/controller decides purpose, necessity, lawful basis, data roles, retention, and whether data may be supplied to a model/vendor. |
| Security and vendor risk | Boundary review and deployment configuration make egress choices inspectable. | Solomon does not secure a host model, endpoint, vendor account, identity system, or data transfer. |
| Accuracy and transparency | Evidence links, verification events, and deterministic currency states make a context decision reconstructable. | Source currency is not legal correctness, factual accuracy, or an explanation of a host model's final output. |
| Rights and correction | Contesting preserves a challenge and blocks default reuse pending appropriate affirmation. | The firm/controller remains responsible for data-subject requests, automated-decision analysis, notices, and remediation. |

## Deployment review evidence

1. Identify controller/processor roles, processing purposes, lawful basis, special-category/criminal-offence data,
   retention, transfers, and vendor terms for the specific route.
2. Record matter-risk criteria, the authorised reviewer, review/sampling rules, escalation path, and evidence of the
   review actually performed.
3. Keep preflight, verification, impact, contest, and audit-pack examples with source/version identifiers.
4. Assess model, API, identity, logging, training/retention, and supply-chain security separately from Solomon.
5. Assess required notices, rights handling, DPIA or other risk assessment, and any automated-decision implications
   with appropriate UK advice.

## Limits

Do not represent Solomon as SRA-approved, ICO-approved, UK GDPR-compliant, secure, or suitable for a specific matter
without deployment-specific evidence and qualified review. Recheck the primary sources before a production decision:
the ICO notes that AI guidance can change with legislation and regulatory updates.
