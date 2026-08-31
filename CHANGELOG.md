<!-- SPDX-License-Identifier: Apache-2.0 -->

# Changelog

All notable changes to Solomon are documented here. This project follows semantic versioning and the
Keep a Changelog structure.

## [Unreleased]

### Added

- Added the Evidence-to-Dependency Proof: a versioned synthetic corpus, deterministic baseline/final evaluation,
  inspectable cited-reliance suggestions, deferred decisions, source-document lineage, and a headless curator proof.
- Added a hash-locked 84-fixture Adversarial Dependency Generalization Proof, raw baseline/final and mutation
  artifacts, two bounded deterministic parser hypotheses, and a headless lifecycle/audit scenario. The final report
  records an explicit evidence-span and mutation-stability gate failure rather than claiming complete generalization.

### Changed

- Dependency suggestions now require an explicit human confirmation before graph-edge creation and currency impact;
  unchanged rejected evidence remains suppressed and revised source documents retain provenance lineage.

## [0.2.0] - Unreleased

### Changed

- Repositioned Solomon as MCP-native currency infrastructure for verified legal knowledge.
- Added MCP-first installation guidance, curator-console guidance, and currency-focused positioning.

### Added

- MCP server and deterministic preflight, impact, explanation, verification, and audit-pack workflows.

### Added

- Initial project foundation, CI, FastAPI shell, Solomon boundary, and Phase 0 ADRs.

## [0.1.0] - 2026-06-11

### Added

- Initial public package version reserved for the first Solomon local/server SKU release.
