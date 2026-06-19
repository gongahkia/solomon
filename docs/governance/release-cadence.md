# Release Cadence

Shisa uses a monthly release train on the first Tuesday of each month.

## Eligibility

A release train can ship only when:

- `main` passes CI
- no `priority/p0` or release-blocker issue remains open
- release notes cover user-visible CLI, config, plugin, packaging, security, and deprecation changes
- changed user-facing docs are merged before the tag
- artifacts are signed and published by the tag-driven release workflow

If any gate fails, skip that month instead of cutting a partial release.

## Release Day

Run the local gate from a clean worktree:

```sh
scripts/monthly-release.sh --tag vX.Y.Z --verify-tag
```

The script runs formatting, schema generation, tests, release build, changelog generation, and GitHub draft-release creation. Use `--dry-run` before the release window to inspect the generated notes and `gh release create` command.

## Timing

- Target: first Tuesday of the month.
- Freeze: label release blockers before the release window.
- Draft: create the GitHub draft release from the signed tag.
- Publish: publish only after artifacts, checksums, SBOMs, Sigstore bundles, Rekor links, and attestations are present.
- Post-release: run `scripts/post-release.sh --released-tag vX.Y.Z` to prepare channel copy and the next development version bump.

## Missed Train

Do not move the date for low-priority work. Missed changes wait for the next first-Tuesday train unless a security advisory or broken release requires an out-of-band patch.

Patch releases must state why they bypassed the monthly train and must run the same gates as the regular release.
