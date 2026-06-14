# Distribution Posture

Decorum is currently a private unpacked-extension prototype.

## Allowed Now

- Local development.
- Manual loading from `dist/` through `chrome://extensions`.
- Small private friend testing with clear disclosure that the tool modifies LinkedIn locally.

## Not Ready Yet

- Chrome Web Store publication.
- Public marketing as "LinkedIn Community Notes."
- Claims that Decorum is affiliated with LinkedIn, X, or Community Notes.
- Remote classifier/retrieval calls from the extension client.

## Before Public Distribution

- Legal/product review of LinkedIn User Agreement risk.
- Naming review that avoids implied affiliation.
- Backend authentication and key isolation.
- Public privacy posture for stored posts, traces, ratings, and false-positive ledger entries.
- A decision on whether this is a private power tool, research prototype, or public extension.

## Current CI Gate

Every branch intended for sharing should pass:

```sh
npm test
npm run build
```

The GitHub Actions workflow runs the same gate on pushes and pull requests targeting `main`.
