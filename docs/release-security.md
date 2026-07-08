# Release Security

Shisa releases use two independent trust layers:

- macOS Developer ID signing plus notarization for macOS archives.
- Stapled macOS DMGs for download validation.
- Sigstore keyless signing for release archives, checksums, and SBOMs.

## GitHub Secrets

The tag-driven release workflow requires these repository secrets for macOS:

- `MACOS_CERTIFICATE_P12`: base64-encoded Developer ID Application `.p12`.
- `MACOS_CERTIFICATE_PASSWORD`: password for the `.p12`.
- `MACOS_KEYCHAIN_PASSWORD`: temporary CI keychain password.
- `MACOS_CODESIGN_IDENTITY`: codesign identity, usually `Developer ID Application: ...`.
- `APPLE_ID`: Apple ID used for notarization.
- `APPLE_TEAM_ID`: Apple developer team ID.
- `APPLE_APP_SPECIFIC_PASSWORD`: app-specific password for notarytool.

Before the first signed release, create the notary profile locally once to verify the credentials:

```sh
xcrun notarytool store-credentials shisa-notary \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD"
```

CI creates the same `shisa-notary` profile on the macOS runner before submitting the archive.

## macOS Signing Flow

On macOS release runners, `.github/workflows/release.yml`:

1. Imports the Developer ID certificate into a temporary keychain.
2. Runs `codesign --deep --options runtime --sign` for `shisa`, `shisad`, and `shisa-supervisor`.
3. Packages the signed files.
4. Submits the archive with `xcrun notarytool submit --wait --keychain-profile shisa-notary`.
5. Builds a macOS DMG from the signed files.
6. Submits the DMG with `xcrun notarytool submit --wait --keychain-profile shisa-notary`.
7. Runs `xcrun stapler staple` and `xcrun stapler validate` on the DMG.

Validate a downloaded macOS tarball binary with:

```sh
codesign -dvv shisa
spctl -a -vv shisa
```

Validate a downloaded macOS DMG with:

```sh
xcrun stapler validate shisa-<tag>-macos-<arch>.dmg
spctl -a -vv -t open shisa-<tag>-macos-<arch>.dmg
```

## Sigstore Assets

For each release archive, checksum, and SBOM, CI publishes:

- `.sigstore.json`: recommended verification bundle.
- `.sig`: detached signature.
- `.pem`: signing certificate.
- `.crt`: certificate alias for tooling that expects a `.crt` suffix.

`shisa update --verify` downloads the archive, `.sig`, `.pem`, and `.crt`, then verifies with:

```sh
cosign verify-blob shisa-<tag>-<os>-<arch>.tar.gz \
  --certificate shisa-<tag>-<os>-<arch>.tar.gz.pem \
  --signature shisa-<tag>-<os>-<arch>.tar.gz.sig \
  --certificate-identity "https://github.com/gongahkia/shisa/.github/workflows/release.yml@refs/tags/<tag>" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

Bundles remain the preferred manual verification path; see [Release Signing](signing.md).
