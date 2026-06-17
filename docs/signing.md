# Release Signing

Shisa release artifacts are signed in the tag-driven release workflow with Sigstore keyless signing. The workflow publishes:

- release archives
- SHA-256 checksum files
- SPDX SBOM files
- cosign bundle files
- `rekor-links.txt`

## Verify A Release File

Download the artifact and its matching bundle from the GitHub Release. Use the exact tag in the certificate identity:

```sh
tag=v0.1.0
artifact="shisa-$tag-macos-arm64.tar.gz"
cosign verify-blob "$artifact" \
  --bundle "$artifact.sigstore.json" \
  --certificate-identity "https://github.com/gongahkia/shisa/.github/workflows/release.yml@refs/tags/$tag" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

Check `rekor-links.txt` for the transparency log URL tied to each bundle.

## Distrust Triggers

Treat a release as distrusted when any of these are true:

- the tag was moved, deleted, or recreated
- the release workflow ran from an unexpected workflow path
- a bundle verifies against an unexpected OIDC issuer
- a GitHub Actions credential or maintainer account used for the release was compromised
- Sigstore publishes an incident covering the signing time window
- the release archive checksum differs from the published checksum

## Distrust Procedure

1. Mark the GitHub Release as compromised in the release notes.
2. Add the tag, artifact names, bundle names, Rekor log indexes, reason, and timestamp to this page.
3. Open a security advisory when user action is required.
4. Remove install instructions that point at the affected tag.
5. Cut a replacement tag only after the release workflow and maintainer access have been reviewed.

## Rotation Procedure

There is no long-lived Shisa signing key. Rotation means changing the GitHub OIDC identity that verifiers trust.

1. Create a new release workflow path, for example `.github/workflows/release-v2.yml`.
2. Keep `id-token: write` scoped to the signing job.
3. Pin the new cosign installer version.
4. Cut a test tag and verify each bundle with the new certificate identity.
5. Update this page with the new verifier string.
6. Publish a release note that states the old identity is distrusted from the stated timestamp.

## Distrusted Releases

No releases are currently distrusted.
