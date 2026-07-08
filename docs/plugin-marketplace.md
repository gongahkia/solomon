# Plugin Marketplace

Shisa's marketplace is a checked-in TOML index. It points to plugin repositories; it does not host plugin code or run a registry service.

## Schema

Entries live in `marketplace/index.toml`:

```toml
[[plugins]]
name = "kubectx"
repo = "gongahkia/shisa-plugin-kubectx"
homepage = "https://github.com/gongahkia/shisa-plugin-kubectx"
version = "0.1.0"
capabilities = ["fs_read", "env_read"]
sigstore_key = "optional-key-or-identity"
status = "community"
description = "Kubernetes k8s current context and namespace prompt segment"
keywords = ["k8s", "kubernetes"]
```

Required fields:

- `name`: Shisa plugin id.
- `repo`: GitHub `owner/repo`, cloned at `version` during validation.
- `homepage`: HTTPS project page.
- `version`: plugin release tag or branch used by marketplace validation.
- `capabilities`: manifest capability names exposed for review.
- `status`: `community`, `official`, or `archived`.

Optional fields:

- `sigstore_key`: signing metadata placeholder until multi-plugin signing policy is active.
- `description`: one-line search text.
- `keywords`: additional search aliases.

## Submission

1. Publish a plugin repo with `plugin.lua`, README, license, and a release tag matching `version`.
2. Keep capabilities narrow and list only capability classes used by the manifest.
3. Add one `[[plugins]]` entry to `marketplace/index.toml`.
4. Run `bash scripts/marketplace-validate.sh`.
5. Open a PR with the validation output and plugin repo link.

Validation clones each repo at the declared version and runs `shisa plugin verify <path>`, which strict-loads the manifest and rejects direct `os.execute` or `io.popen` use.
