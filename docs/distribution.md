# Distribution Posture

Decorum is currently a private unpacked-extension prototype.

## Decision

Decorum stays private and research-only. Do not publish it to the Chrome Web Store or market it as a public LinkedIn extension unless LinkedIn grants written permission or a later legal review approves a different path.

This is not legal advice. It is the product decision for the current prototype based on LinkedIn's current public terms reviewed on 2026-07-10.

## LinkedIn User Agreement Risk

LinkedIn's User Agreement, effective 2025-11-03, creates direct distribution risk for this product shape:

- Section 8.2(2) prohibits developing, supporting, or using browser plugins/add-ons or other technology to scrape or copy LinkedIn services, profiles, or other data.
- Section 8.2(4) prohibits copying, using, displaying, or distributing information obtained from the services without the content owner's consent.
- Section 8.2(10) prohibits implying LinkedIn affiliation or endorsement without express consent.
- Section 8.2(15) prohibits overlaying or otherwise modifying the services or their appearance, including inserting elements or removing, covering, or obscuring ads.

[Inference] Decorum's core behavior inserts a local context card into the LinkedIn feed UI. Even when it does not automate engagement, bypass access controls, or export scraped datasets, that insertion is enough to keep public distribution out of scope.

## Allowed Now

- Local development.
- Manual loading from `dist/` through `chrome://extensions`.
- Small private friend testing when each tester receives the disclosures below before install.

## Required Tester Disclosures

Private testers must be told:

- Decorum is unaffiliated with LinkedIn, X, or Community Notes.
- Decorum modifies the LinkedIn page locally by inserting context cards under detected posts.
- LinkedIn may restrict accounts or access for activity it treats as violating its terms.
- The prototype is for research feedback only, not work-critical or public distribution use.
- The local prototype stores detected post text, classifier request/response metadata, trace IDs, thresholds, and ratings in browser local storage.
- Testers should not use it on confidential, employer-sensitive, regulated, or legally privileged LinkedIn content.
- Testers can remove it at any time from `chrome://extensions`.

## Not Ready Yet

- Chrome Web Store publication.
- Public marketing as "LinkedIn Community Notes."
- Claims that Decorum is affiliated with LinkedIn, X, or Community Notes.
- Remote classifier/retrieval calls from the extension client.
- Any claim that the extension is compliant with LinkedIn's User Agreement.

## Before Public Distribution

- Written legal/product approval that explicitly addresses LinkedIn User Agreement sections 8.2(2), 8.2(4), 8.2(10), and 8.2(15).
- A decision on whether to seek written permission from LinkedIn before publication.
- Follow the naming rules in [naming.md](./naming.md).
- Backend authentication and key isolation.
- Public privacy posture for stored posts, traces, ratings, and false-positive ledger entries.
- A public-facing disclosure flow for what the extension reads, stores, sends, renders, and modifies.
- A takedown/disable plan if LinkedIn changes selectors, policy, or enforcement posture.

## Current CI Gate

Every branch intended for sharing should pass:

```sh
npm test
npm run build
```

The GitHub Actions workflow runs the same gate on pushes and pull requests targeting `main`.

## Sources Reviewed

- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- LinkedIn Professional Community Policies: https://www.linkedin.com/legal/professional-community-policies
- LinkedIn Privacy Policy: https://www.linkedin.com/legal/privacy-policy
