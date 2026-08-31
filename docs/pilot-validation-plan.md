<!-- SPDX-License-Identifier: Apache-2.0 -->

# Pilot Validation Plan

No external pilot validation had occurred when issues #1, #2, #3, and #5 were retired on 2026-08-31. Their reviewer prompts are preserved here as hypotheses, not evidence or endorsements.

## Bounded scenario

Use a synthetic or approved non-privileged internal-knowledge subset containing a known authority change, two confirmed direct dependencies, at least one transitive dependency, an unaffected comparison item, and a matter/client scope boundary. A facilitator records the authority event, participants inspect default and review-mode retrieval, inspect `why` and the audit pack, then complete or reject a review decision. Do not claim legal correctness, prevented loss, production readiness, model safety, or confidentiality compliance from this session.

## Personas and questions

| Persona | Hypothesis from retired issue | Questions | Success signal |
|---|---|---|---|
| Lawyer/reviewer | #1 stale explanations communicate a review obligation without adjudicating | What changed? Why is review due? Does any wording imply a legal conclusion? | participant accurately states “flag, do not adjudicate” and identifies the next human action |
| Curator/knowledge owner | #2 confirmed dependency capture is fast enough and evidence spans inspire calibrated trust | How hard is it to add/confirm an edge? Is the citation span sufficient? What is missing? | participant completes the edge workflow and identifies any required provenance field |
| Matter lead, GC, or risk owner | #3 currency reports and audit material support governance questions | Which report fields support review prioritization? Which privilege, retention, or accountability fields are missing? | participant can identify affected scope, state, rationale, and responsible reviewer without reading raw logs |
| Security/privacy operator | #5 boundary and audit evidence explain what crossed a boundary and what did not | What proof is needed for identity/mapping handling? What audit gap remains? | participant distinguishes code behavior from deployment evidence and writes a bounded gap |

## Data to collect

- Participant role and prior familiarity, not client names or privileged content.
- Task completion time and observable workflow errors.
- Whether the participant correctly distinguishes a dependency flag from a legal conclusion.
- Required fields, confusing labels, trust concerns, and counterexamples.
- Whether the scenario’s affected/unaffected set and matter/client scope behave as the participant expects.
- Explicit consent for any recording; otherwise retain structured notes only.

Store raw feedback in the firm’s approved research location, not in the public repository. Summarize only de-identified findings and the test fixture/version used.

## Process for turning feedback into work

1. Facilitator classifies each observation as usability, documentation, correctness defect, security/privacy concern, unsupported claim, or adoption evidence.
2. Reproduce a correctness or security claim against the deterministic fixture before creating an engineering issue.
3. Create one issue per independently actionable defect with user action, expected/actual behavior, scope, acceptance criterion, and affected fixture/version. Do not create a feature issue for a single unvalidated preference.
4. Put non-actionable comments and rejected hypotheses in the pilot report with the reason they were not converted.
5. Link any resulting issue to the pilot report and update the public roadmap only with de-identified, verified conclusions.

## Prohibited claims

This plan does not validate legal advice, citator quality, authority-feed completeness, confidentiality compliance, zero data retention by a third party, avoided loss, time savings, adoption, or deployment readiness. Those require separately designed evidence and, where applicable, counsel, security, procurement, and customer approval.
