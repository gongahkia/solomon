# Zed Bridge

The scaffold lives at `contrib/editor-bridges/shisa-zed/`.

## Manifest

Zed extension manifests are `extension.toml` files. The Shisa scaffold uses the required metadata fields documented by Zed:

| Field | Value |
| --- | --- |
| `id` | `shisa` |
| `name` | `Shisa` |
| `version` | `0.0.1` |
| `schema_version` | `1` |
| `authors` | `["Shisa contributors"]` |
| `description` | `Shisa editor bridge metadata for Zed.` |
| `repository` | `https://github.com/gongahkia/shisa` |

The manifest ID and name avoid `zed` and `extension` because Zed's publishing prerequisites reject those words in IDs and names.

## Local Dev Install

In Zed, use `zed: install dev extension` from the command palette and select `contrib/editor-bridges/shisa-zed/`.

This scaffold has metadata only. It does not include Rust, WebAssembly, status UI, or Shisa socket integration.

## Marketplace Publish

Publish through a pull request to `zed-industries/extensions`:

1. Add this repository as an HTTPS submodule under `extensions/shisa`.
2. Add an `extensions.toml` entry:

```toml
[shisa]
submodule = "extensions/shisa"
path = "contrib/editor-bridges/shisa-zed"
version = "0.0.1"
```

3. Keep the submodule checked out to a branch commit, not a detached commit.
4. Run `pnpm sort-extensions` in the Zed extensions repo before submitting.

The Zed docs require the license file to reside at the extension `path` when `path` is used. This scaffold links `contrib/editor-bridges/shisa-zed/LICENSE` to the repo MIT license.

## Signing

As of 2026-06-17, Zed's developing-extensions docs document PR review, CI, public HTTPS submodules, local testing, and license validation as publish gates. I found no signing, certificate, or notarization step on that page. Re-check the official docs before submitting a marketplace PR.

References:

- https://zed.dev/docs/extensions/developing-extensions
- https://github.com/zed-industries/extensions
