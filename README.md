# Decorum

Decorum is a Manifest V3 browser extension that adds restrained, Community-Notes-style context cards under LinkedIn posts.

The implementation follows the product constraints in [IDEA.md](./IDEA.md): no overlay, one note per post, high confidence before rendering, and an audit trail for every shown note.

## Development

```sh
npm run check
npm run build
```

Load the generated `dist/` folder from `chrome://extensions` with Developer Mode enabled.

See [docs/implementation-notes.md](./docs/implementation-notes.md) for current architecture decisions and platform risks.

## Current Scope

The first implementation pass is intentionally local-first:

- MV3 extension shell
- LinkedIn content script entrypoint
- Local tonal classifier rendered under detected posts that clear the confidence gate
- Chrome side panel shell
- Local settings storage

Remote model calls and retrieval are not bundled into the client until the trust, cost, and key-management boundaries are explicit.
