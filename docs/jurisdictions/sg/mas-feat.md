<!-- SPDX-License-Identifier: Apache-2.0 -->

# MAS FEAT and financial-services advisory work

Checked: 2026-07-12. This is a research and design note, not financial-regulatory advice, a MAS compliance assessment,
or a statement that a deployment satisfies a financial institution's controls.

## Primary sources

- [MAS: FEAT Principles (2019 PDF)](https://www.mas.gov.sg/-/media/MAS/News-and-Publications/Monographs-and-Information-Papers/FEAT-Principles-Updated-7-Feb-19.pdf)
- [MAS Annual Report 2023/24 remarks: FEAT, Veritas, and AI governance](https://www.bis.org/review/r240722d.htm)

MAS describes FEAT as fairness, ethics, accountability, and transparency principles co-created with the financial
industry for AI and data analytics. In 2024 remarks, MAS said the MAS-led Veritas consortium developed an assessment
methodology and toolkit to help financial institutions assess alignment with FEAT. MAS also described current work on
AI-model, technology, cyber-risk practices and an industry AI Governance Handbook. The principles are relevant where a
law firm advises a financial institution or handles an AI-supported financial-services matter; they do not convert a
law firm or Solomon into a regulated financial institution.

## Design mapping

| FEAT theme | Solomon contribution | Boundary |
| --- | --- | --- |
| Fairness | Evidence/version history and contestability expose a context source and allow a challenge to its currency state. | Solomon does not evaluate discriminatory outcomes, data/model bias, suitability, or fairness of a financial decision. |
| Ethics | Boundary review and scoped retrieval constrain context selection and egress. | [Inference] The institution defines ethical standards, risk appetite, and prohibited uses. |
| Accountability | Actor-attributed verification, affirmation, contest, and audit events preserve review evidence. | Solomon does not assign board/senior-management accountability or take responsibility for a financial outcome. |
| Transparency | `why`, impact paths, and audit packs explain a Solomon source-currency decision. | This is not a customer explanation or transparency assessment for a host model, financial product, or decision. |

## Advisory deployment evidence

1. Identify whether the use case is by or for a regulated financial institution, financial product/service, or customer decision.
2. Map the model, data, vendor, human-oversight, validation, monitoring, and incident controls outside Solomon.
3. Preserve source/evidence, preflight, verification, contest, and audit outputs for the relevant advice workflow.
4. Obtain the institution's current FEAT/Veritas, technology-risk, model-risk, data-governance, and sectoral-control evidence.

## Limits

Do not market Solomon as MAS-approved, FEAT-aligned, fair, ethical, accountable, transparent, or suitable for a
financial-services use case without deployment-specific evidence and qualified regulatory review.
