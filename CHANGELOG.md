# Changelog

## Unreleased

### Changed

- Shisa has been refocused from a shell prompt into a local target-contract verifier for direct Kubernetes and Terraform/OpenTofu commands.

### Added

- `shisa target list`, `inspect`, and `run`.
- User-owned `targets.toml` contracts for Kubernetes context/namespace/cluster server and Terraform workspace.
- Expected, observed, source, and verdict output, including JSON for inspection automation.

### Removed

- Prompt rendering, shell hooks, daemon/supervisor, themes, importers, plugins, VCS/language modules, cloud displays, command-risk heuristics, benchmark product, and their documentation and CI.

This is intentionally a breaking product change. Git history retains the removed implementation.
