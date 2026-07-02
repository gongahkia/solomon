# Decorum

Decorum is a Manifest V3 browser extension that adds restrained, Community-Notes-style context cards under LinkedIn posts.

The implementation keeps the core product constraints in the code and docs: no overlay, one note per post, high confidence before rendering, and an audit trail for every shown note. Open roadmap items are tracked in GitHub issues.

## Development

```sh
npm run check
npm test
npm run build
```

Load the generated `dist/` folder from `chrome://extensions` with Developer Mode enabled.

See [docs/implementation-notes.md](./docs/implementation-notes.md) for current architecture decisions and platform risks.
See [docs/gateway/classifier-gateway.md](./docs/gateway/classifier-gateway.md) for the remote classifier boundary.
See [docs/distribution.md](./docs/distribution.md) for the current private-prototype distribution posture.

## Current Scope

The first implementation pass is intentionally local-first:

- MV3 extension shell
- LinkedIn content script entrypoint
- Local tonal classifier rendered under detected posts that clear the confidence gate
- Chrome side panel shell
- Local settings, detected-post history, note ledger, and ratings
- Chromium runtime fixture test for detection, insertion, gating, unique traces, and rating persistence
- Visual snapshot test for the rendered note card

Remote model calls and retrieval are not bundled into the client until the trust, cost, and key-management boundaries are explicit.

## Tests

`npm test` runs:

- Static manifest and JavaScript syntax checks.
- A Chromium fixture test against `tests/fixtures/linkedin-feed.html`.
- A visual snapshot comparison for the note card; the current PNG artifact is written to `.tmp/visual/note-card.png`.

Update the visual baseline only after intentional visual changes:

```sh
DECORUM_UPDATE_VISUAL=1 npm run test:visual
```
