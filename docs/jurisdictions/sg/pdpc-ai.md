<!-- SPDX-License-Identifier: Apache-2.0 -->

# Singapore AI governance and Solomon

Checked: 2026-07-12. This is a design note, not certification, legal advice, or an AI Verify assessment.

## Primary sources

- [PDPC: Singapore's approach to AI governance](https://www.pdpc.gov.sg/help-and-resources/2020/01/model-ai-governance-framework)
- [AI Verify Foundation](https://aiverifyfoundation.sg/)

The PDPC describes the Model AI Governance Framework as practical guidance for private-sector AI deployment. Its
stated guiding principles are human-centric AI and decisions that are explainable, transparent, and fair. PDPC also
describes AI Verify as a governance-testing framework and toolkit; neither source makes a product automatically
compliant merely because it records audit evidence.

## Design mapping

| Governance concern | Solomon contribution | Boundary |
| --- | --- | --- |
| Internal governance and roles | Verification, contest, affirm, and pin events identify a human/system actor and evidence reference. | [Inference] The firm still assigns authority, oversight, escalation, and accountability. |
| Human involvement | Stale-pending-reverification, contested, and superseded states prevent default reuse and route review to a lawyer. | Solomon does not choose the appropriate level of human oversight. |
| Explainability and transparency | `why`, impact results, dependency paths, and audit packs expose the source and currency reasons for a context decision. | Explainability of a host model's final answer remains the host's responsibility. |
| Repeatability and reproducibility | Deterministic primitive plans, hashes, and event history support reconstruction of a Solomon decision. | Reproduction requires preserved deployment inputs and does not prove legal correctness. |
| Data governance and security | Scoped retrieval, boundary review, local-only routing, and metadata-only audit design reduce uncontrolled context flow. | Firm/vendor security, data quality, retention, transfer, and access controls require separate assessment. |
| Feedback and remediation | Contestability preserves challenges and quarantines proposed corrections until appropriate human affirmation. | The firm must define complaint, remediation, and incident processes. |

## Suggested evidence pack for an internal AI-governance review

1. Deployment architecture and host/model data-flow diagram.
2. Scope and remote-egress policy for each matter class.
3. Boundary test results and residual-risk register.
4. Example preflight, verification, impact, and audit-pack outputs.
5. Actor/role matrix for affirmations, contests, and incident escalation.
6. Vendor, retention, transfer, security, and legal review records outside Solomon.

## Limits

AI governance principles are not a substitute for a firm's regulatory, professional, contractual, or data-protection
analysis. Do not market Solomon as AI Verify-certified, PDPC-approved, fair, or compliant without independent
evidence for the specific deployment.
