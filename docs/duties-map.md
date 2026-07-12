# Duties Map

Checked: 2026-07-12

Scope: issue #15 R18. This is a product-positioning map, not legal advice.
`[Inference]` marks claims about how Solomon helps satisfy a duty.

## Duties

| Duty source | Duty | Solomon support |
|---|---|---|
| ABA Formal Opinion 512 / Model Rule 1.1 | Competence; understand benefits and risks of GAI tools. | [Inference] Verification desk, currency checks, contradiction flags, and audit packs make AI-adjacent risk review explicit before reliance. |
| ABA Formal Opinion 512 / Model Rule 1.6 | Confidentiality for current, former, and prospective client information. | [Inference] Boundary review, scoped retrieval, redaction-first examples, and zero-egress/local-model modes reduce unnecessary disclosure paths. |
| ABA Formal Opinion 512 / Model Rule 1.4 | Communication and consultation about means used for client objectives. | [Inference] Audit packs and partner-facing currency reports give concrete artifacts lawyers can explain to clients or supervisors. |
| ABA Formal Opinion 512 / Model Rule 1.5 | Reasonable fees; do not bill clients for tool-learning time. | [Inference] Audit trails separate machine-assisted checks from lawyer review work, supporting fee narrative discipline. |
| Law Society of Singapore AI advisory | Do not upload privileged, proprietary, confidential, or personal data to public AI tools; anonymise/redact correctly. | [Inference] Boundary gates and no-public-AI default routing support this workflow. Solomon still requires firm policy and user discipline. |
| Law Society of Singapore AI advisory | Review terms, retention/model-training defaults, and cyber safeguards. | [Inference] Deployment checklist should require approved model endpoints and documented retention settings before enabling non-local models. |
| Singapore PDPA | Compliance, policies/practices, consent/purpose/notification, accuracy, protection, retention, transfer, breach notification. | [Inference] Scoped storage, provenance, authority versioning, and audit logs support compliance evidence, but PDPA obligations remain firm-owned. |
| ICO AI/data-protection guidance | AI/data-protection risk assessment, explanation, auditing, and accountable processing. | [Inference] Currency explanations and evidence packs support explainability and post-hoc audit of AI-context decisions. |
| SRA Effective Supervision guidance | AI-assisted or AI-generated work requires appropriate human review, scrutiny, and professional judgement; an authorised individual retains ultimate responsibility. | [Inference] Solomon's currency states, verification evidence, and audit packs make a review checkpoint visible, but do not discharge supervision duties. |

## Product Implications

- Default posture: preflight before model use, not post-hoc clean-up.
- Default data path: local/scoped retrieval first; external model only after
  boundary clearance.
- Required evidence: authority version, dependency chain, stale reason,
  impacted matter/client scope, actor, timestamp, and exported audit pack.
- Required wording: Solomon flags risk and currency; it does not decide the law.

## Sources

- ABA: <https://www.americanbar.org/news/abanews/aba-news-archives/2024/07/aba-issues-first-ethics-guidance-ai-tools/>
- Law Society of Singapore: <https://www.lawsociety.org.sg/law-society-advisory-on-the-use-of-publicly-available-ai-tools-pdf-link/>
- Singapore PDPA: <https://sso.agc.gov.sg/Act/PDPA2012>
- PDPC AI governance: <https://www.pdpc.gov.sg/organisations/resources/guidance-by-topic/singapores-approach-to-ai-governance>
- ICO AI/data protection: <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/>
- SRA Effective Supervision: <https://www.sra.org.uk/solicitors/guidance/effective-supervision-guidance/>
