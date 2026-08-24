# Distribution plan

Close Enough is not yet publicly released. The repository currently supports source installation from a clone with Go 1.25 or newer. No Homebrew, WinGet, or AUR package should be advertised until the first signed public release exists.

## First public release

The `v0.1.0` release must publish versioned macOS, Linux, and Windows archives; `checksums.txt`; Sigstore bundles; SBOMs; license-audit reports; and the two verified installers. The release workflow already produces these assets, but a public release and its assets have not yet been exercised because GitHub Actions is blocked by the repository account's billing state.

After those assets are published, validate each installer against the immutable GitHub release URL on a clean macOS/Linux and Windows environment. The repository's tests already exercise the installer logic against local HTTP release fixtures; that does not prove a public GitHub asset is reachable or signed with the production workflow identity.

## Package-manager rollout

| Channel | Status | Release prerequisite |
| --- | --- | --- |
| Go | Ready after tagging | Publish a public semantic-version tag; users install `github.com/gongahkia/close-enough/cmd/close-enough@vX.Y.Z`. |
| Direct archive | Ready after tagging | Publish the signed archives, checksums, bundles, and installers. |
| Homebrew | Planned | Create the owner-maintained `homebrew-close-enough` tap and add a formula with the two macOS archive URLs and SHA-256 digests. |
| WinGet | Planned | Submit a manifest referencing stable public Windows installer assets and their SHA-256 hash, then test install and uninstall through WinGet. |
| AUR | Planned | Publish an owner-maintained `PKGBUILD` that builds from a signed source tag or verifies a release archive. |

Do not publish placeholder formulas or manifests: every package must resolve to an immutable public version, verify its expected digest where the ecosystem supports it, expose `close-enough version`, and have an uninstall path. Keep this document in sync with the release workflow and the public README.
