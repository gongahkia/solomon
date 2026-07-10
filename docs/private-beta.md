# Private Beta Runbook

Reviewed: 2026-07-10.

Scope: 5 invited testers, unpacked Chrome extension only, no Chrome Web Store, no public marketing.

## Maintainer Preflight

1. Start from a clean branch.
2. Run:

```sh
npm run check
npm run test:contracts
npm run test:gateway
npm run test:retrieval
npm run test:classifier
npm run build
```

3. Share the generated `dist/` folder as a zipped folder with each tester.
4. Send the disclosure below before the install instructions.
5. Assign each tester a private tester code such as `beta-01`; do not collect LinkedIn credentials.

## Required Disclosure

Send this text before install:

```text
Decorum is an unaffiliated private prototype. It is not made by, endorsed by, or connected to LinkedIn, X, or Community Notes.

Decorum modifies LinkedIn locally in your browser by inserting context cards under detected LinkedIn posts. LinkedIn may restrict accounts or access if it treats that behavior as violating its terms.

Use it only for research feedback. Do not use it on confidential, employer-sensitive, regulated, or legally privileged LinkedIn content.

This local build stores detected post text, note text, classifier metadata, trace IDs, thresholds, sources, and your ratings in Chrome local extension storage. It does not ask for your LinkedIn password or LinkedIn cookies.

You can remove it at any time from chrome://extensions.
```

## Tester Install Instructions

1. Unzip the `dist/` folder.
2. Open Chrome.
3. Go to `chrome://extensions`.
4. Turn on Developer mode.
5. Click Load unpacked.
6. Select the unzipped `dist/` folder.
7. Confirm Decorum appears in the extensions list.
8. Open `https://www.linkedin.com/feed/`.
9. Browse normally for 15-20 minutes.
10. When a Decorum card appears, use the rating buttons.
11. Open the Decorum side panel from the extension icon and check the local ledger.
12. Remove the extension from `chrome://extensions` when done.

## Feedback To Collect

Collect one response per tester:

- Tester code.
- Chrome version and macOS/Windows version.
- Install friction: exact step that failed or caused hesitation.
- Whether Decorum appeared in `chrome://extensions`.
- Whether LinkedIn loaded normally after install.
- Number of Decorum notes seen.
- Trace IDs for any false positives.
- Rating labels used.
- Missed-note examples: post URL, short redacted post excerpt, and expected note type.
- UX feedback: card placement, wording, rating buttons, side panel, ledger, and removal flow.
- Privacy/disclosure concerns.

Do not collect LinkedIn passwords, cookies, private messages, or unredacted confidential posts.

## Follow-Up Issue Routing

Create one GitHub issue per actionable finding with the `Private beta feedback` issue template.

Routing:

- Install cannot complete: `bug`, high priority.
- LinkedIn page breaks or slows down: `bug`, high priority.
- False positive: `bug`; include trace ID and rating label.
- Missed note: `enhancement`; include redacted post excerpt and expected note type.
- Confusing wording or placement: `enhancement`.
- Privacy or disclosure concern: `question`.

Every follow-up issue should include:

- tester code
- browser/OS
- Decorum commit SHA
- build date
- affected trace ID, if any
- redacted evidence
- expected behavior
- proposed next action

## Exit Criteria

- 5 testers received the disclosure.
- 5 testers attempted install, or every install blocker has a GitHub issue.
- Every reported false positive has a trace ID or a note explaining why no trace ID was available.
- Every missed-note example is redacted and filed as a follow-up issue.
- UX feedback is grouped into actionable GitHub issues.
- No expansion beyond 5 testers until follow-up issues are triaged.
