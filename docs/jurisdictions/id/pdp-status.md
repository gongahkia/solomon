<!-- SPDX-License-Identifier: Apache-2.0 -->

# Indonesia PDP Law: implementation status

Checked: 2026-07-12. This is a source-status note, not legal advice, an implementation-status determination for a
particular deployment, or a compliance assessment.

## Verified primary sources

- [JDIH Kemkomdigi: Law No. 27 of 2022 on Personal Data Protection](https://jdih.komdigi.go.id/produk_hukum/view/id/832/t/undangundang%2Bnomor%2B27%2Btahun%2B2022)
- [JDIH BPK status record for Law No. 27 of 2022](https://peraturan.bpk.go.id/Details/229798/uuno-27-tahun-2022)
- [Komdigi 2025 performance report](https://eppid.komdigi.go.id/attachments/045866d0b76dd70f7000f8747bdf5e1e8e059b90a1a5a81aa9eb6c7068bcb920/fa1898f3b7f2672c03afd8682a6187d1ece86d3114c6a1a52d8a51fe86a81ae0.pdf)
- [Komdigi 2025 RPP PDP harmonisation notice](https://jdih.komdigi.go.id/berita/view/105)
- [Government Regulation No. 71 of 2019](https://jdih.komdigi.go.id/produk_hukum/view/id/695/t/peraturan%2Bpemerintah%2Bnomor%2B71%2Btahun%2B2019)

The official records identify Law No. 27 of 2022 as the Personal Data Protection Law, in force from 17 October 2022.
Its transition provision gave controllers, processors, and other relevant parties two years from promulgation to align.
The JDIH BPK record also lists the Constitutional Court's conditional reading of Article 53(1)(b); use the current
official text rather than a static summary.

## Implementation status

As of this check, the primary implementing Government Regulation (`RPP PDP`) is not treated here as enacted. Komdigi
reported that it sent the draft to the President through the State Secretariat on 6 October 2025, followed by interagency
initialling and a December 2025 confirmation meeting. The same 2025 report says the Personal Data Protection Body draft
presidential regulation remained in harmonisation and would continue in 2026, with a target of presidential adoption.

That report further says Komdigi performs PDP functions, including digital-space compliance supervision, while the PDP
Body has not yet been formed. A May 2025 official notice separately records harmonisation of the RPP PDP. These are
status records for drafts and administrative activity, not proof that either draft has become binding law.

Law No. 27 itself assigns several operational details to a Government Regulation, including data-protection impact
assessment, data-protection officer/function, cross-border transfer, administrative-sanction procedure, and the PDP
Body's powers. Article 75 preserves pre-existing data-protection rules only to the extent they do not conflict with the
Law; PP 71/2019 remains a relevant electronic-systems source, not a substitute for the unfinalised PDP implementation
regulation.

## Transfer and localisation boundary

The Law's transfer sequence is the primary source: an overseas transfer requires an equivalent or higher protection
level, then adequate and binding protection if that condition is not met, then the data subject's consent if neither is
available. The Law leaves further transfer detail to a Government Regulation. This note does not infer a general data-
localisation rule, an approved-country list, a vendor-transfer mechanism, or an AI-host outcome from those provisions.

## Solomon boundary

| Topic | Solomon contribution | Boundary |
| --- | --- | --- |
| Scoped handling | Boundary review and local-only routing can limit uncontrolled context flow. | [Inference] The controller/operator determines legal basis, scope, roles, rights handling, retention, transfer, and vendor obligations. |
| Evidence | Verification, contest, impact, and audit events preserve a source-currency record. | This is not PDP compliance evidence for a host model or deployment. |
| Security | Deployment controls and boundary checks make selected handling choices inspectable. | Solomon does not secure vendors, infrastructure, credentials, storage, or cross-border access. |

## Deployment consequence

Do not enable an Indonesia jurisdiction profile from this note. Before deployment, obtain current Indonesian advice and
verify the official enacted regulation register, regulator/body status, sectoral rules, controller/processor allocation,
legal basis, sensitive-data treatment, rights, incidents, retention, and the specific transfer route.
