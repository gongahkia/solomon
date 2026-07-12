<!-- SPDX-License-Identifier: Apache-2.0 -->

# Singapore PDPA and model-bound legal knowledge

Checked: 2026-07-12. This is a product-design research note, not legal advice or a determination that a deployment
complies with the Personal Data Protection Act 2012 (PDPA).

## Primary sources

- [Personal Data Protection Act 2012](https://sso.agc.gov.sg/Act/PDPA2012/) — current consolidated statute.
- [PDPC data-protection obligations](https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act/data-protection-obligations) — obligation overview.
- [PDPC advisory guidelines on key concepts](https://www.pdpc.gov.sg/-/media/Files/PDPC/PDF-Files/Advisory-Guidelines/AG-on-Key-Concepts/Advisory-Guidelines-on-Key-Concepts-in-the-PDPA-1-Oct-2021.pdf?la=en) — operational guidance, including transfers.

## Clauses relevant to a law-firm AI deployment

| PDPA area | Relevance to a model-bound workflow | Solomon control or evidence | Residual decision |
| --- | --- | --- | --- |
| ss 11-12, accountability and policies/practices | The firm remains responsible for appropriate policies, governance, complaint handling, and accountable data handling. | [Inference] Audit metadata, deployment diagnostics, and boundary decisions can support an internal evidence trail. | Firm policy, DPO governance, vendor due diligence, and incident processes remain outside Solomon. |
| ss 13-17, consent and exceptions | Collection, use, or disclosure of client/matter content to a model requires an identified lawful basis; an exception cannot be assumed from a product setting. | Boundary review reduces content sent to a model and records metadata about the decision. | Determine the applicable basis, any professional obligations, notices, and instructions for each matter. |
| ss 18 and 20, purpose limitation and notification | Model egress, retrieval, and reuse must remain within notified/authorised purposes. | Scope fields, provenance, preflight context, and deterministic plans make the purpose-relevant request traceable. | Confirm purpose compatibility and notices; do not treat logging as notification or consent. |
| ss 23-24, accuracy and protection | A firm needs accurate personal data where decisions or disclosures depend on it, and reasonable security arrangements. | Verification states and boundary controls distinguish reviewed knowledge from stale or contested material. | Assess security controls across client, host, storage, model provider, identity, and operations. |
| s 25, retention limitation | Personal data must not be retained when no longer needed for legal or business purposes. | Metadata-only audit design and volatile boundary mappings can reduce retention exposure. | Set and enforce matter, legal-hold, retention, deletion, backup, and vendor-retention schedules. |
| s 26, transfer limitation | An overseas model, endpoint, support operation, or subprocesser may be a transfer requiring comparable protection or another valid path. | Local-only routing and explicit remote-egress policy can prevent accidental remote use; endpoint decisions are auditable. | Determine transfer path, recipient, contract/assurance, applicable exceptions, and jurisdictional requirements. |
| ss 26B-26D, breach assessment and notification | A compromise affecting personal data may trigger assessment and notification duties. | Audit journal and scoped identifiers may help reconstruction. | Operate a tested incident process; Solomon does not perform breach assessment or notification. |

## Deployment implications

1. Treat an external model call as a distinct disclosure/transfer decision, not merely a feature toggle.
2. Bind matter/client scope before retrieval and minimize the model-bound context.
3. Keep remote egress disabled by default until the firm documents its lawful basis, vendor terms, transfer analysis,
   retention, security, and human-review procedure.
4. Preserve enough metadata to investigate a decision without assuming metadata is free of personal-data risk.
5. Reassess the design when model providers, endpoints, subprocessors, retention terms, or data flows change.

## Limits

This note does not resolve whether a particular item is personal data, whether a statutory exception applies, whether
a specific transfer satisfies the PDPA, or how privilege/professional obligations interact with a deployment. Obtain
Singapore-qualified advice and review the current primary sources before production use.
