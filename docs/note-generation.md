# Note Generation Policy

Reviewed: 2026-07-10.

This is product posture, not legal advice.

## Decision

Next milestone: AI-only visible notes.

Users may rate Decorum notes with fixed labels, but they may not write public notes, edit model notes, request notes for other users, or vote notes into visibility. User-contributed and hybrid note generation are deferred until there is a moderation queue, public replay ledger, abuse handling, privacy notice, takedown path, and contributor eligibility model.

## Rationale

[Inference] AI-only visible notes are the smallest next step because the current product already has classifier contracts, confidence gates, source attachments, ratings, and a replay ledger.

[Inference] User-contributed or hybrid notes add a second product: contributor identity, free-text moderation, brigading controls, contributor reputation, appeal flows, public status changes, and source-quality review.

Community-note systems are not just note text plus ratings. Recent Community Notes research describes contributor-written notes, contributor ratings, bridging-style selection, post-display instability, and human feedback bottlenecks. Decorum does not have that governance layer yet.

## Moderation Implications

Under AI-only mode:

- No tester free text is published in the LinkedIn page.
- Ratings use fixed labels only: useful, incorrect, unfair tone read, and too noisy.
- A model note is shown only when it clears the confidence threshold.
- Factual notes need cited HTTP(S) sources.
- Negative ratings enter the eval queue; they do not immediately hide notes for other testers.
- Gateway replay rows keep enough request/response data to review disputed notes.

Still required:

- weekly false-positive review before expanding tester count
- source allowlist/blocklist review for factual retrieval
- redaction before shared debug logs
- takedown path for any private-beta tester report

Deferred until user-contributed or hybrid mode:

- contributor identity and eligibility
- public note drafts
- public author attribution or pseudonyms
- contributor strike/reputation system
- spam and harassment moderation
- coordinated-rating detection
- appeal and correction workflow

## Abuse Implications

AI-only mode leaves these abuse paths:

- a tester can spam ratings
- a tester can trigger expensive gateway calls
- a model can produce a noisy, unfair, or unsupported note
- a retrieved source can be low quality

Mitigations for the next milestone:

- one active rating per note trace per tester
- per-tester classifier and retrieval quotas from `docs/cost-model.md`
- no public rating counts
- no free-text rating field
- model/source metadata in every replay row
- manual review of all negative ratings during beta

## Privacy Implications

Ratings are product feedback, not public contribution. Store them as eval labels tied to tester/install ID and note trace ID.

Private-beta storage may include post text, post URL, classifier request/response, sources, threshold snapshot, rating label, timestamp, and false-positive flag. Do not store LinkedIn cookies, LinkedIn credentials, LinkedIn session data, or provider API keys.

Before remote sync beyond private beta:

- disclose what post text and ratings are stored
- document retention period
- add tester export/delete path
- redact post author identity where review does not need it
- keep rating labels separate from any public ledger identity

## Liability Implications

AI-only does not remove risk. It centralizes visible note authorship in Decorum's system, so generated statements need conservative gating, factual sourcing, and replay review.

Visible notes must not:

- claim legal, medical, hiring, credit, or employment eligibility conclusions
- assert motive or character of the post author
- state private facts without cited public sources
- frame a rating as community consensus
- imply LinkedIn or X affiliation

Use plain copy that labels the card as Decorum-generated context. Funding-announcement notes must show sources. Tonal notes must stay about writing pattern, not author intent.

## Rating Eval Loop

Existing ratings feed evaluation only:

- `useful`: positive example for current rubric and threshold.
- `incorrect`: false-positive example; review prompt, retrieval source, and classifier output.
- `unfair_tone_read`: tone-safety failure; raise threshold or add negative rubric example.
- `too_noisy`: product-quality failure; review trigger precision and note copy.

Weekly beta review:

- export ledger rows with negative ratings
- replay classifier responses from stored request/response data
- mark each negative rating as model error, retrieval error, source error, copy error, or user disagreement
- update eval fixtures before lowering thresholds or expanding tester count
- keep all visible generation AI-only until negative-rating rate is reviewed below the beta threshold selected for rollout

## References

- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- LinkedIn Professional Community Policies: https://www.linkedin.com/legal/professional-community-policies
- X Community Notes guide: https://communitynotes.x.com/guide/en/about/introduction
- Consensus Stability of Community Notes on X: https://arxiv.org/abs/2601.14002
- How Human Feedback Shapes AI-generated Community Notes: https://arxiv.org/abs/2606.30905
