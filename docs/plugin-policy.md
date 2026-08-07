# Plugin Distribution Policy

Shisa does not operate a plugin catalog or remote installer. Plugin authors distribute a source directory or a `.shisa-plugin` bundle through their own release channel; users choose the exact local path they install.

## Distribution Requirements

Published plugins should:

- expose a valid `plugin.lua` manifest
- use a license compatible with redistribution
- declare all capabilities narrowly
- keep network, exec, secrets, and pre-exec access off unless the feature needs them
- document user-visible side effects
- avoid collecting telemetry by default

Plugins that handle secrets, cloud accounts, kubeconfigs, SSH config, or production context must describe their local data flow in the README.

Bundles must be produced with `shisa plugin pack`. Installation verifies the bundle payload hashes, manifest name/version, and included Ed25519 signature. This validates bundle structure and detects accidental corruption; it does not establish author identity because the public key travels inside the bundle.

## Verified Badge

`verified` means a locally installed plugin has been marked after maintainer review for capability scope and obvious abuse. It does not mean the code is bug-free, safe for every environment, or endorsed for production use.

Verified status can be removed when a plugin changes ownership, expands sensitive capabilities, stops publishing source, or has unresolved security reports.

## Moderation

Maintainers may remove a local `verified` marker or withdraw an official recommendation for:

- malware, credential theft, or covert telemetry
- misleading names that impersonate Shisa or another maintainer
- unsafe default behavior
- capability declarations that do not match behavior
- abandoned security reports
- harassment or abuse tied to the plugin project

The status change is reversible when the owner fixes the issue and publishes a reviewable release.

## Appeals

Plugin owners may request a renewed review with a regular project issue once they have published a reviewable remediation. Requests must include the plugin id, disputed action, and remediation evidence.
