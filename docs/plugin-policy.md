# Plugin Policy

Shisa's plugin marketplace is a directory of user-owned repositories. A listing does not transfer maintenance, liability, or review ownership to core maintainers.

## Listing Requirements

Marketplace entries must:

- expose a valid `plugin.lua` manifest
- use a license compatible with redistribution
- declare all capabilities narrowly
- keep network, exec, secrets, and pre-exec access off unless the feature needs them
- document user-visible side effects
- avoid collecting telemetry by default

Plugins that handle secrets, cloud accounts, kubeconfigs, SSH config, or production context must describe their local data flow in the README.

The static marketplace index is published from `docs/plugins/index.json` to `https://shisa.sh/plugins/index.json`. Entries stay out of the index until the repository URL and manifest can be reviewed.

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

Plugin owners may appeal by opening a governance issue or using the private project contact once configured. Appeals must include the plugin id, repository, disputed action, and remediation evidence.
