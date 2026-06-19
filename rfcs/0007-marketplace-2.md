# RFC-0007: Marketplace 2.0

- Status: Draft
- Created: 2026-06-19
- Owner: core maintainers
- Area: plugin marketplace

## Summary

Marketplace 2.0 upgrades the static plugin index from a minimal discovery list into a signed, auditable metadata channel for plugins and official packs. It keeps plugin repositories user-owned while adding stronger provenance, review state, capability summaries, issue routing, and compatibility metadata.

## Motivation

The v1 marketplace index lists plugin URLs, manifest hashes, and signatures. That is enough for search/install, but not enough for users to answer:

- who owns this plugin now?
- which Shisa versions is it compatible with?
- which capabilities changed since the last reviewed version?
- where should bugs be filed?
- was this plugin delisted, superseded, or compromised?
- does this plugin ship as source only or as a signed `.shisa-plugin` bundle?

Marketplace 2.0 should answer those questions without turning core maintainers into owners of third-party plugins.

## Design

### Index Shape

The v2 index is still static JSON published from the repo or release artifacts, but it is split into:

- `plugins/index.v2.json`: compact search/install index
- `plugins/<plugin-id>.json`: per-plugin metadata document
- `plugins/packs/<pack-id>.json`: official pack metadata document

The top-level index contains only stable lookup fields:

```json
{
  "version": 2,
  "updated": "2026-06-19",
  "plugins": [
    {
      "name": "git-tools",
      "kind": "plugin",
      "metadata_url": "plugins/git-tools.json",
      "latest": "0.4.1",
      "verified": true,
      "capability_summary": ["fs_read", "exec"],
      "status": "listed"
    }
  ]
}
```

Per-plugin metadata contains:

| Field | Meaning |
| --- | --- |
| `name` | Plugin id matching manifest rules. |
| `owner` | Current maintainer identity and repository URL. |
| `issue_tracker` | Primary issue URL; required for graduated packs. |
| `versions` | Reviewed versions with manifest hash, bundle hash, signatures, API compatibility, and capability summary. |
| `review` | `unreviewed`, `reviewed`, `verified`, `delisted`, or `compromised`. |
| `capability_diff` | Capability changes from the prior reviewed version. |
| `advisories` | Known security or compatibility advisories. |
| `replaces` | Prior plugin ids superseded by this plugin. |

### Signing

The v2 index and each metadata document must be signed. A valid install path verifies:

1. index signature
2. per-plugin metadata signature
3. manifest hash
4. bundle hash when installing `.shisa-plugin`
5. Minisign or Sigstore plugin signature

The CLI must fail closed when a required signature is absent or mismatched. Direct local path installs remain allowed for development but must be labeled as unverified.

### Capability Review

Marketplace 2.0 records capability diffs as user-facing metadata. When a plugin upgrade expands `fs_read`, `fs_watch`, `exec`, `net`, `secrets`, `env_read`, or `pre_exec`, `shisa plugin install` and `shisa plugin trust` must present the diff before the user can continue.

Sensitive capability expansion removes `verified` until reviewed again.

### Official Packs

Official packs use the same metadata shape plus:

- pack lifecycle state from `docs/pack-status.md`
- pack performance budget id
- pack issue tracker
- pack owner
- compatibility window
- threat-model review link

A pack cannot be `graduated` in the marketplace while its issue tracker, pack budget, or threat-model metadata is missing.

### Search And Install

`shisa plugin search` reads the v2 index by default once v2 ships. Search should rank exact name matches first, then verified plugins, then recency. It must not fetch arbitrary plugin code during search.

`shisa plugin install <name>` resolves:

1. marketplace name
2. metadata document
3. selected version
4. source repo or bundle URL
5. signature checks
6. manifest validation
7. capability prompt

The CLI should preserve `--index <path>` for offline or private indexes.

## Performance

Search must operate on the compact index without downloading every plugin metadata document. Install can fetch one metadata document and one source/bundle target.

The daemon prompt path must not read marketplace metadata. Marketplace sync is a CLI/install-time concern.

## Security

Marketplace metadata is supply-chain input. v2 must:

- pin hashes for manifests and bundles
- sign index and metadata documents
- preserve owner and signature history for review
- fail closed on unsigned or downgraded metadata
- record delisting and compromise states
- avoid running plugin code during search
- keep direct URL/path installs clearly separate from verified marketplace installs

## Compatibility

The v1 index remains readable through a compatibility path during migration. A v2-capable CLI should prefer `index.v2.json` when present and fall back to `index.json` with a warning that richer provenance metadata is unavailable.

Existing installed plugins keep their local trust state. Capability expansion still requires a new trust decision after metadata sync.

## Rejected Alternatives

- Centralize plugin code under the Shisa org: clearer ownership, but too much maintenance and liability.
- Use a dynamic registry service: unnecessary for v2 and harder to mirror.
- Trust repository tags only: tags do not describe capabilities, review state, or marketplace moderation.
- Fetch all metadata during search: slower and leaks more network behavior than needed.

## Unresolved Questions

- Whether marketplace signatures should use one root key, threshold signatures, or Sigstore-only identity.
- Whether plugin install should support TUF-style delegated metadata.
- Whether popularity or download counts belong in a no-analytics marketplace.
- How private organization indexes should compose with the public index.
