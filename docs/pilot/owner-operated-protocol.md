<!-- SPDX-License-Identifier: Apache-2.0 -->

# Owner-Operated Pilot Protocol

## Status and claim boundary

**Prepared, not performed.** This protocol may be run only after the repository owner authorizes a small,
non-sensitive corpus. A completed run is an owner-operated pilot / structured self-evaluation, not external
validation, legal-accuracy evidence, production adoption, or reviewer-usability validation.

Solomon must be described accurately throughout: **flag, not adjudicate**. It records provenance, dependency,
currency, and review signals; it does not decide whether a legal position is correct or what legal action to take.

## Entry criteria

Before running any task, the owner records outside Git:

- written authorization for this limited self-evaluation;
- a corpus small enough for direct owner review and confirmed non-sensitive, non-privileged, and non-client-specific;
- a disposable or otherwise owner-approved deployment and recovery location;
- a named owner/operator and the intended scope boundary;
- a statement that raw documents, screenshots, timings tied to people, free-text notes, and source evidence remain in
  the approved private pilot location;
- the [results template](./owner-operated-results-template.md), copied to that private location before the session.

Do not run this protocol on unknown, privileged, personal, regulated, client, production, or mixed-sensitivity data.
Do not commit raw pilot data. Only an owner-approved, de-identified summary may later be committed.

## Pre-registered expectations

Before registering the planned source change, write the following in the private results record. Do not revise these
fields after observing Solomon's impact result; additions require a timestamped amendment and an explanation.

| Required pre-registration | Minimum content |
| --- | --- |
| source change | a non-sensitive source identifier, planned change, and planned time |
| expected dependencies | the exact reviewed dependency resources expected to be relevant, plus their scope |
| expected impacted resources | direct, transitive, and deliberately unaffected resources expected before the change |
| expected review action | whether a human would reaffirm, supersede, retire, defer, or record insufficient evidence |
| success/failure interpretation | what would count as useful, irrelevant, missing, confusing, or unsafe output |

The planned change may proceed only after this table is complete. The owner must retain the pre-change version,
authority/source identity, and scope so evidence reconstruction can be evaluated without putting content in Git.

## Session procedure and measurements

Use a single owner-operated session at first. Record elapsed times with the same clock, the start/end event, and any
pause or restart. “Not performed” is a valid value; do not invent a value to complete the template.

| Step | Owner action | Required observation |
| --- | --- | --- |
| setup and registration | deploy or open the approved instance; register the source and scope | setup/deployment time, source-registration time, configuration or identity friction |
| governed assertion | create or inspect a human-governed dependency assertion with evidence | assertion completion time, evidence sufficiency, and whether the owner can explain pending versus confirmed state |
| comprehension check | answer in the owner’s own words: “What does flag, not adjudicate mean here?” | pass only if the answer says Solomon identifies review work but does not decide legal correctness or action; otherwise record a comprehension failure |
| evidence reconstruction | use preserved provenance, source/version information, and audit/`why` material to reconstruct why a confirmed dependency exists | reconstruction time, missing context, confidence, and any misleading or unusable evidence link |
| planned source change | make the pre-registered non-sensitive change, then inspect the scoped impact | expected versus observed direct/transitive/unaffected resources; impact usefulness; missing and irrelevant impacts |
| suggestions, if used | inspect suggestion output without treating it as an edge | suggestion count, irrelevant suggestions, missing useful suggestions, review burden, and whether any wording implies automatic trust |
| reverification or supersession | perform the selected human review action after inspecting impact and evidence | time, clarity of next action, ability to explain the result, and retained provenance/currency state |
| recovery observation | only in a disposable clone or separately approved recovery exercise, inspect restart/backup/restore friction | operator recovery friction, unresolved state, documentation gaps, and whether an operator action was required |

For impact usefulness, compare the observed set with the pre-registered set before deciding whether it was useful. For
suggestion burden, record suggestions separately from confirmed edges; an unconfirmed suggestion must never be
counted as an impact-producing dependency.

## Debrief and disposition

Record operator friction, recovery friction, trust concerns, confusing labels, missing evidence, irrelevant impact,
unexpected scope behavior, and qualitative failures. Classify each observation as a documentation issue, usability
hypothesis, correctness/security incident, unsupported claim, or no action. Reproduce any correctness or security
concern on a non-sensitive fixture before creating engineering work.

Do not publish or claim external validation, legal accuracy, production adoption, reviewer usability, time savings,
confidentiality compliance, or legal advice. The owner may approve a short redacted summary only after checking that
it contains no raw source content, personal/client identifiers, credentials, private paths, or unapproved feedback.
