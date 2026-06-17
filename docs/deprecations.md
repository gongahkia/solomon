# Deprecations

This page tracks user-facing deprecations for CLI flags, config fields, plugin API fields, theme keys, shell hooks, and documented file paths.

## One-Major-Overlap Rule

When Shisa deprecates a user-facing interface, the old interface stays supported for one full major release after the replacement ships.

Example:

- `1.4.0` ships `new_key` and deprecates `old_key`.
- Every `1.x` release still accepts `old_key` and prints a warning.
- `2.0.0` may remove `old_key`.

Exceptions require an RFC when the change affects security, data loss, or daemon startup. Security removals can be faster, but the release note must state the risk and migration path.

## Required Deprecation Entry

Each deprecation entry must include:

- interface name
- replacement
- first deprecated version
- last supported major version
- warning surface
- migration command or manual steps
- linked RFC or issue

## Warning Surfaces

Deprecations should appear in every relevant surface:

- `shisa doctor`
- config validation diagnostics
- command help text
- plugin lint output
- release notes

## Active Deprecations

No active deprecations.
