<!-- SPDX-License-Identifier: Apache-2.0 -->

# Law Society of Singapore AI guidance

Checked: 2026-07-12. This note summarises the [Law Society's Advisory on the Use of Publicly Available AI Tools](https://www.lawsociety.org.sg/law-society-advisory-on-the-use-of-publicly-available-ai-tools-pdf-link/), dated 2 April 2026. It is not legal advice or a substitute for the Legal Profession (Professional Conduct) Rules 2015, client instructions, or firm policy.

## Current guidance

The advisory warns that public, including generative, AI tools may expose lawyers to confidentiality breaches. It
recommends reviewing terms of use, preferring paid/enterprise tools for professional work only after appropriate
review, and ensuring tool use does not breach professional obligations.

For public AI tools, the advisory says not to upload or input privileged, proprietary, confidential, or personal data.
It calls for anonymisation/removal of client confidential information and cautions that visual “blackout” may leave
underlying machine-readable text. It also directs users to understand retention/model-training defaults and opt out
where necessary, and to check adequate cybersecurity safeguards.

## Solomon implications

| Advisory concern | Solomon support | Limit |
| --- | --- | --- |
| No privileged/confidential/personal data in public prompts | Boundary review, scoped retrieval, pseudonymisation, and local-only default routing can reduce exposure. | [Inference] A boundary result is not a guarantee that a prompt contains no protected information. |
| Anonymise/redact correctly | Pseudonymisation, reidentification, and document-scrub paths preserve a reviewable workflow. | Users must verify source documents, images, attachments, and host context independently. |
| Review terms, retention, training, and security | Endpoint/egress policy and metadata-only audit evidence can support an approval record. | Solomon cannot read, accept, or enforce a provider's terms, retention, or subprocessors. |
| Professional judgement remains with lawyer | Currency flags, verification states, contestability, and audit packs expose a review checkpoint. | Solomon does not decide legal correctness or discharge professional duties. |

## Operational checklist

1. Classify the host/model as public, enterprise, local, or otherwise approved before a matter is connected.
2. Document the terms, retention/training setting, data location/transfer, security review, and permitted data classes.
3. Use scope controls and boundary review before prompt assembly; fail closed on policy or boundary failure.
4. Require human verification when authority movement, contest, or supersession makes prior knowledge non-current.
5. Retain deployment evidence in the firm's governance process; do not rely on an audit log alone.

The advisory states that more detailed guidance was being prepared. Recheck the Law Society source before relying on
this note for a production workflow.
