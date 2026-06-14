# Implementation Notes

## Product Shape

`IDEA.md` is the source of truth. Decorum is a LinkedIn feed browser extension, not a general LinkedIn automation tool. The primary surface is a single restrained context card inserted under a post after the detector has enough signal.

Current implementation status:

- MV3 extension shell with a Chrome side panel.
- Content script that detects likely LinkedIn feed post containers, starting with `.feed-shared-update-v2`.
- Local tonal classifier note card under posts that clear the confidence gate.
- Local settings, detected-post history, shown-note ledger, and note ratings in `chrome.storage.local`.
- Chromium runtime test proving detection, insertion under the flagged post, one-note behavior, threshold/disable reactivity, unique trace IDs, and rating persistence.
- Visual snapshot test covering note-card dimensions, key computed styles, header wording, and rendered PNG hash.

## Platform Decisions

- The extension uses static MV3 `content_scripts` for LinkedIn feed/post URLs because the target is a known host and the product needs to react to infinite-scroll feed mutations.
- The side panel uses `side_panel.default_path` plus the `sidePanel` permission. This follows Chrome's current Side Panel API shape.
- The MVP ledger uses `chrome.storage.local`, not SQLite. SQLite is still the right long-term audit shape for a backend or packaged local service, but it is not a native MV3 browser-extension primitive. The storage schema keeps trace IDs and replayable note metadata so it can migrate to SQLite or D1 later.
- Model and retrieval calls are not in the client yet. Putting Anthropic or Exa keys in a content script would leak them. The local classifier uses a background-worker adapter boundary so a future gateway-backed Haiku implementation can replace the deterministic rules without changing the content-script rendering contract.

## Risk Register

- LinkedIn DOM selectors are unstable. The detector deliberately uses selector fallbacks and marks scanned nodes to avoid repeat work, but `.feed-shared-update-v2` can break without notice.
- LinkedIn's User Agreement prohibits modifying the service appearance by inserting elements. Keep this as an unpacked, private prototype until the distribution posture is reviewed.
- The local tonal classifier is deterministic and conservative. It is useful for validating the product loop, but it should not be treated as equivalent to the planned Haiku/Sonnet classifier.
- The visual snapshot prevents accidental drift in this repo, but it is not proof that the card exactly matches live X Community Notes. A browser comparison against real X notes is still needed before making that claim.
- Public naming should avoid "LinkedIn Community Notes" because it creates unnecessary brand and affiliation risk.

## Verification

Run the full local verification suite with:

```sh
npm test
npm run build
```

The runtime test uses a generated localhost extension manifest so the real content scripts can run against `tests/fixtures/linkedin-feed.html`. The production manifest remains restricted to LinkedIn feed/post URLs.

## References Checked

- Chrome content scripts: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts
- Chrome Side Panel API: https://developer.chrome.com/docs/extensions/reference/api/sidePanel
- Chrome Storage API: https://developer.chrome.com/docs/extensions/reference/api/storage
- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- Anthropic model overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Exa pricing: https://exa.ai/pricing
