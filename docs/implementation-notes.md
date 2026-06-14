# Implementation Notes

## Product Shape

`IDEA.md` is the source of truth. Decorum is a LinkedIn feed browser extension, not a general LinkedIn automation tool. The primary surface is a single restrained context card inserted under a post after the detector has enough signal.

Current implementation status:

- MV3 extension shell with a Chrome side panel.
- Content script that detects likely LinkedIn feed post containers, starting with `.feed-shared-update-v2`.
- Prototype note card under the first detected post.
- Local settings, detected-post history, shown-note ledger, and note ratings in `chrome.storage.local`.

## Platform Decisions

- The extension uses static MV3 `content_scripts` because the target is a known host and the product needs to react to infinite-scroll feed mutations.
- The side panel uses `side_panel.default_path` plus the `sidePanel` permission. This follows Chrome's current Side Panel API shape.
- The MVP ledger uses `chrome.storage.local`, not SQLite. SQLite is still the right long-term audit shape for a backend or packaged local service, but it is not a native MV3 browser-extension primitive. The storage schema keeps trace IDs and replayable note metadata so it can migrate to SQLite or D1 later.
- Model and retrieval calls are not in the client yet. Putting Anthropic or Exa keys in a content script would leak them. The next implementation should use either a small gateway or an explicit local-development key path before Haiku/Exa are wired.

## Risk Register

- LinkedIn DOM selectors are unstable. The detector deliberately uses selector fallbacks and marks scanned nodes to avoid repeat work, but `.feed-shared-update-v2` can break without notice.
- LinkedIn's User Agreement prohibits modifying the service appearance by inserting elements. Keep this as an unpacked, private prototype until the distribution posture is reviewed.
- The prototype note is intentionally labeled as a placement test. It should not make a real tonal or factual accusation until the classifier and confidence gate are implemented.
- Public naming should avoid "LinkedIn Community Notes" because it creates unnecessary brand and affiliation risk.

## References Checked

- Chrome content scripts: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts
- Chrome Side Panel API: https://developer.chrome.com/docs/extensions/reference/api/sidePanel
- Chrome Storage API: https://developer.chrome.com/docs/extensions/reference/api/storage
- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- Anthropic model overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Exa pricing: https://exa.ai/pricing
