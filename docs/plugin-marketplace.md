# Plugin Catalog

Shisa's plugin catalog is a checked-in TOML index. It points to local example plugin directories in this repo; it does not run a registry service.

## Schema

Entries live in `marketplace/index.toml`:

```toml
[[plugins]]
name = "kubectx"
path = "examples/plugins/kubectx"
homepage = "https://github.com/gongahkia/shisa/tree/main/examples/plugins/kubectx"
version = "0.1.0"
capabilities = ["fs_read", "fs_watch", "env_read"]
sigstore_key = "optional-key-or-identity"
status = "official"
description = "Kubernetes k8s current context and namespace prompt segment"
keywords = ["k8s", "kubernetes"]
```

Required fields:

- `name`: Shisa plugin id.
- `path`: relative path to the plugin directory.
- `version`: plugin manifest version used by catalog review.
- `capabilities`: manifest capability names exposed for review.
- `status`: `community`, `official`, or `archived`.

Optional fields:

- `homepage`: HTTPS project page.
- `sigstore_key`: signing metadata placeholder until multi-plugin signing policy is active.
- `description`: one-line search text.
- `keywords`: additional search aliases.

## Adding Entries

1. Add a plugin directory with `plugin.lua`, README, and license.
2. Keep capabilities narrow and list only capability classes used by the manifest.
3. Add one `[[plugins]]` entry to `marketplace/index.toml` with a local `path`.
4. Run `bash scripts/marketplace-validate.sh`.
5. Open a PR with the validation output.

Validation runs `shisa plugin verify <path>`, which strict-loads the manifest and rejects direct `os.execute` or `io.popen` use.
