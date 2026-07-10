# Plugin Signing

Catalog entries may include `sigstore_key` metadata while signing remains review-only. The TOML index does not enforce signatures during install yet.

## Minisign

Use Minisign's prehashed signature format:

```sh
minisign -Sm plugin.lua -t 'shisa-plugin:<plugin-id>:<manifest-sha256>'
```

Historical Minisign review metadata used:

- `scheme`: `minisign`
- `public_key`: the `RW...` Minisign public key
- `signature_url`: URL for `plugin.lua.minisig`
- `trusted_comment`: the signed comment, expected to include the plugin id and manifest hash

## Sigstore

Use a Sigstore bundle for `plugin.lua` or its digest. During review, `sigstore_key` may record the expected identity or key reference.

Shisa treats signatures as listing metadata until a verifier is wired into install. Maintainers must verify signatures before adding or updating signed catalog entries.

Sources: [Minisign](https://jedisct1.github.io/minisign/), [Sigstore Bundle Format](https://docs.sigstore.dev/about/bundle/).
