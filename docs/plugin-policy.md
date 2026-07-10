# Plugin Catalog Policy

Shisa's plugin catalog is a directory of local example plugins in this repo. External plugin repositories can still be installed directly by URL, but they are not catalog entries.

## Listing Requirements

Catalog entries must:

- expose a valid `plugin.lua` manifest
- use a license compatible with redistribution
- declare all capabilities narrowly
- keep network, exec, secrets, and pre-exec access off unless the feature needs them
- document user-visible side effects
- avoid collecting telemetry by default

Plugins that handle secrets, cloud accounts, kubeconfigs, SSH config, or production context must describe their local data flow in the README.

The catalog index is checked in at `marketplace/index.toml`. Entries stay out of the index until the local path, manifest, capability list, and optional signing metadata can be reviewed.

## Verified Badge

`verified` means the latest submitted manifest passed maintainer review for identity, capability scope, and obvious abuse. It does not mean the code is bug-free, safe for every environment, or endorsed for production use.

Verified status can be removed when a plugin changes ownership, expands sensitive capabilities, stops publishing source, or has unresolved security reports.

## Moderation

Maintainers may delist or hide plugins for:

- malware, credential theft, or covert telemetry
- misleading names that impersonate Shisa or another maintainer
- unsafe default behavior
- capability declarations that do not match behavior
- abandoned security reports
- harassment or abuse tied to the plugin project

Delisting is reversible when the owner fixes the issue and publishes a reviewable release.

## Appeals

Plugin owners may appeal with a regular project issue once the plugin has published a reviewable remediation. Appeals must include the plugin id, disputed action, and remediation evidence.
