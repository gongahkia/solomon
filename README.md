# Decorum

Decorum is an unaffiliated Manifest V3 browser extension prototype that adds restrained context cards under LinkedIn posts.

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
See [docs/cost-model.md](./docs/cost-model.md) for remote model, retrieval, and rollout quotas.
See [docs/note-generation.md](./docs/note-generation.md) for the AI-only note-generation decision.
See [docs/ledger.md](./docs/ledger.md) for the shared replay ledger and false-positive surface.
See [docs/visual-parity.md](./docs/visual-parity.md) for the X Community Notes visual comparison.
See [docs/distribution.md](./docs/distribution.md) for the current private-prototype distribution posture.
See [docs/private-beta.md](./docs/private-beta.md) for the 5-tester unpacked-extension beta runbook.
See [docs/naming.md](./docs/naming.md) for naming and affiliation rules.

## Current Scope

The first implementation pass is intentionally local-first:

- MV3 extension shell
- LinkedIn content script entrypoint
- Local tonal classifier rendered under detected posts that clear the confidence gate
- Optional gateway classifier path with local fallback
- Optional gateway factual retrieval for funding-announcement claims
- Chrome side panel shell
- Local settings, detected-post history, note ledger, and ratings
- Chromium runtime fixture test for detection, insertion, gating, unique traces, and rating persistence
- Visual snapshot test for the rendered note card

Provider model calls and retrieval are not bundled into the extension client; remote classification goes through the gateway boundary.

## Tests

`npm test` runs:

- Static manifest and JavaScript syntax checks.
- Gateway classifier contract tests.
- Funding retrieval contract tests.
- A Chromium fixture test against `tests/fixtures/linkedin-feed.html`.
- A visual snapshot comparison for the note card; the current PNG artifact is written to `.tmp/visual/note-card.png`.

Update the visual baseline only after intentional visual changes:

```sh
DECORUM_UPDATE_VISUAL=1 npm run test:visual
```
