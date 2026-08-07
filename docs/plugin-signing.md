# Plugin Bundle Integrity

`shisa plugin pack <path>` creates a `.shisa-plugin` tar bundle. The bundle records every payload file's SHA-256 value and an Ed25519 signature over a canonical manifest of those values. `shisa plugin install ./plugin.shisa-plugin` verifies both before installing.

The current signature is an integrity check, not publisher identity: the bundle contains its own public key. Obtain the bundle from a release channel you trust and review declared capabilities before installation.

## Publisher identity

Authors who need independently verifiable publisher identity should sign release artifacts outside Shisa. Minisign is one suitable option:

```sh
minisign -Sm plugin.lua -t 'shisa-plugin:<plugin-id>:<manifest-sha256>'
```

## Sigstore

Sigstore bundles are also appropriate for publisher identity. Shisa does not currently consume Minisign or Sigstore metadata at install time; verify those signatures in the publisher's documented release workflow.

Sources: [Minisign](https://jedisct1.github.io/minisign/), [Sigstore Bundle Format](https://docs.sigstore.dev/about/bundle/).
