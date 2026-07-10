# Implementation Notes

## Product Shape

Decorum is a LinkedIn feed browser extension, not a general LinkedIn automation tool. The primary surface is a single restrained context card inserted under a post after the detector has enough signal. Open roadmap items are tracked in GitHub issues.

Current implementation status:

- MV3 extension shell with a Chrome side panel.
- Content script that detects likely LinkedIn feed post containers, starting with `.feed-shared-update-v2`.
- Local tonal classifier note card under posts that clear the confidence gate.
- Optional gateway-backed classifier path that can call a Decorum REST gateway while preserving the local classifier as the default fallback.
- Optional Exa-backed funding-announcement retrieval through the gateway; cited sources render only when confidence clears the threshold.
- Local settings, detected-post history, shown-note ledger, and note ratings in `chrome.storage.local`.
- Shared ledger design that preserves replay data while keeping public false-positive rows redacted.
- Versioned classifier request/response contract with eval fixtures and gateway examples.
- Chromium runtime test proving detection, insertion under the flagged post, one-note behavior, threshold/disable reactivity, unique trace IDs, and rating persistence.
- DOM-resilience test covering alternate LinkedIn-like post containers, fallback IDs, nested post-like blocks, and unrelated DOM churn.
- Visual snapshot test covering note-card dimensions, key computed styles, Community Notes reference tokens, header wording, and rendered PNG hash.

## Platform Decisions

- The extension uses static MV3 `content_scripts` for LinkedIn feed/post URLs because the target is a known host and the product needs to react to infinite-scroll feed mutations.
- The side panel uses `side_panel.default_path` plus the `sidePanel` permission. This follows Chrome's current Side Panel API shape.
- The MVP ledger uses `chrome.storage.local`, not SQLite. SQLite is still the right long-term audit shape for a backend or packaged local service, but it is not a native MV3 browser-extension primitive. The storage schema keeps trace IDs, full post text, classifier request/response metadata, threshold snapshots, and rating outcomes so it can migrate to SQLite or D1 later.
- Provider model and retrieval calls are not in the client. Putting Anthropic or Exa keys in a content script would leak them. The optional gateway classifier sends the versioned classifier request to a Decorum gateway and renders nothing on gateway failure or malformed responses. Funding-announcement retrieval also runs gateway-side and stores cited sources in the classifier response and ledger. The local deterministic classifier remains the default dev/test fallback.
- Background storage writes are serialized to avoid concurrent `chrome.storage.local` updates overwriting detected-post or ledger entries.
- The shared ledger design uses private encrypted replay blobs plus redacted public rows. False positives are top-level ledger rows with the same visual weight as shown notes.
- The detector performs an initial scan, then scans only added DOM subtrees that look like LinkedIn post containers. Metrics are exposed through document data attributes for fixture tests.

## Risk Register

- LinkedIn DOM selectors are unstable. The detector deliberately uses selector fallbacks and marks scanned nodes to avoid repeat work, but `.feed-shared-update-v2` can break without notice.
- LinkedIn's User Agreement prohibits modifying the service appearance by inserting elements. Keep this as an unpacked, private prototype until the distribution posture is reviewed.
- The local tonal classifier is deterministic and conservative. It is useful for validating the product loop, but it should not be treated as equivalent to the planned Haiku/Sonnet classifier.
- [Inference] The visual snapshot prevents accidental drift in this repo, but it is not proof that the card exactly matches live X Community Notes. A browser comparison against real X notes is still needed before making that claim.
- The 2026-07-10 visual parity review matched the note card against captured public X Community Notes screenshots. Some product-specific differences remain documented.
- Public naming uses "Decorum" and avoids "LinkedIn Community Notes" because it creates unnecessary brand and affiliation risk.
- Visible notes stay AI-only for the next milestone. Ratings are eval labels, not user-contributed note text.
- CI disables strict PNG byte-hash comparison because Chrome builds can render antialiasing differently. It still checks computed visual tokens and dimensions.

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
- Note generation policy: ./note-generation.md
- Shared ledger design: ./ledger.md
- Visual parity review: ./visual-parity.md
