<!-- SPDX-License-Identifier: Apache-2.0 -->

# Boundary coverage audit

Checked: 2026-07-12 against the current local boundary implementation. This is an implementation audit, not legal
advice, a jurisdictional compliance assessment, or evidence that a detector satisfies any statutory obligation.

## Common detectors

Every reviewed route runs the common PII and risk detectors: names, organisations, email, phone, Singapore-format
national IDs, passport/bank/card/IMEI (validated where applicable), date of birth, IP/MAC, employee/customer/medical
references, special-category markers, minors, cross-border markers, consent/erasure markers, and data-minimisation
markers. It also runs financial amounts, percentages, and an MNPI/high-risk lexicon.

These are lexical safeguards, not a complete entity-recognition or legal-classification system. A miss, hit, or
severity does not determine whether information is personal data, inside information, privileged, confidential, or
transferable.

## Reviewed jurisdiction packs

| Pack | Current PII terms/detectors | Current MNPI terms | Status |
| --- | --- | --- | --- |
| SG | `NRIC`, `FIN`, common detectors, labelled UEN and IRAS references, and Myinfo identity-field markers. | `SFA section 218`, `inside information`, plus common MNPI lexicon. | Implementation coverage only; Singapore profile work remains open. |
| MY | `MyKad`, `PDPA Malaysia`, common detectors, and labelled MyKad/MyPR and SSM 12-digit-registration patterns. | `CMSA sections 188-189`, plus common MNPI lexicon. | Implementation coverage only; Malaysia profile work remains open. |
| UK | `National Insurance`, common detectors, and NI/labelled UTR/Companies House/NHS patterns. | `UK MAR`, `inside information`, plus common MNPI lexicon. | Implementation coverage only; additional UK profile work remains open. |
| EU | `GDPR special category`, plus common detectors. | `MAR Article 7`, `inside information`, plus common MNPI lexicon. | Implementation coverage only; EU profile design remains open. |

Jurisdictional strict terms can originate from either source or destination pack. The engine marks the four listed
market-abuse terms as high-severity `MNPI`; other strict terms are medium-severity `PII` markers. This is a routing
signal, not a legal conclusion.

## Identifier sources

- [ACRA UEN guidance](https://www.acra.gov.sg/resources/guides-forms/applying-for-special-uen/)
- [IRAS GST search identifier examples](https://mytax.iras.gov.sg/ESVWeb/default.aspx?lang=en&target=GSTListingSearch)
- [IRAS CRS tax-reference guide](https://www.iras.gov.sg/media/docs/default-source/uploadedfiles/pdf/iras-xml-schema-user-guide-for-crs-return-%28fourth-edition%29.pdf?sfvrsn=403f9e36_4)
- [Singpass Myinfo personal data catalogue](https://docs.developer.singpass.gov.sg/docs/data-catalog-myinfo/catalog/personal)

## Known gaps

1. No per-jurisdiction CLI/MCP/console profile exists; callers pass source and destination codes to the boundary route.
2. No jurisdiction pack is certified against the complete text of its privacy, market-abuse, professional, or sectoral rules.
3. Pattern matching does not establish identity, controller/processor role, privileged status, consent, transfer basis,
   or notification duties.
4. Additional identifier coverage and jurisdiction-profile configuration remain open.
