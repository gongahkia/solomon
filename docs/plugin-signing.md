# Plugin Signing

Marketplace entries must pin the submitted `plugin.lua` with `manifest_sha256` and at least one signature record.

## Minisign

Use Minisign's prehashed signature format:

```sh
minisign -Sm plugin.lua -t 'shisa-plugin:<plugin-id>:<manifest-sha256>'
```

The marketplace entry records:

- `scheme`: `minisign`
- `public_key`: the `RW...` Minisign public key
- `signature_url`: URL for `plugin.lua.minisig`
- `trusted_comment`: the signed comment, expected to include the plugin id and manifest hash

## Sigstore

Use a Sigstore bundle for `plugin.lua` or its digest. The marketplace entry records:

- `scheme`: `sigstore`
- `bundle_url`: URL for the Sigstore bundle JSON
- `certificate_identity`: expected signing identity
- `certificate_issuer`: expected OIDC issuer

Shisa treats signatures as listing metadata until a verifier is wired into install. Maintainers must verify signatures before adding or updating marketplace entries.

Sources: [Minisign](https://jedisct1.github.io/minisign/), [Sigstore Bundle Format](https://docs.sigstore.dev/about/bundle/).
