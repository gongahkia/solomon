# Visual Parity Review

Reviewed: 2026-07-10.

## Evidence

Captured public X Community Notes screenshots reviewed:

- The Poke D-Day note: https://www.thepoke.com/2024/01/16/community-note-on-d-day-comment-goes-straight-into-hall-of-fame/
- VIEW Journal Figure 6, sourced to the X Community Notes guide: https://viewjournal.eu/articles/10.18146/view.324
- FIJ dark-mode Stake note screenshot: https://fij.ng/article/stake-watermark-rave-on-x-spells-doom-for-addicted-gamblers/

## Matched Tokens

[Inference] The matched tokens below come from captured screenshot evidence and the regenerated local card artifact.

- Long desktop header copy: "Readers added context they thought people might want to know."
- White light-mode card background: `#ffffff`.
- X text color: `#0f1419`.
- X blue link/icon color: `#1d9bf0`.
- Border color: `#cfd9de`.
- Pale header strip: `#f7f9f9`.
- Header weight: `700`.
- Rounded card: `16px`.
- Header/body/rating areas separated by thin dividers.
- Blue people icon in the header.

## Intentional Differences

- Decorum keeps fixed rating labels instead of X's single "Rate it" button because beta ratings feed eval categories.
- Decorum shows confidence and retrieval/source status in the card body; X's public card does not expose model confidence.
- Decorum keeps the expandable "Why flagged" trace inline for replay and debugging.
- Decorum does not show X copy that says context is written by people who use X because Decorum notes are AI-generated for the next milestone.
- Decorum stays unaffiliated and does not use X, LinkedIn, or Community Notes branding in product naming.

## Test Status

Intentional parity changes updated:

- `extension/src/content/note-card.js`
- `extension/src/content/note-card.css`
- `tests/visual/x-community-notes-reference.json`
- `scripts/test-visual.mjs`

`npm run test:visual` is currently blocked in this environment: sandboxed runs cannot bind localhost, and escalated Google Chrome headless runs do not inject the MV3 content scripts. The failure occurs before visual comparison.
