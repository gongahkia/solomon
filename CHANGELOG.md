# Changelog

All notable changes to Shisa are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/). Public releases use `vMAJOR.MINOR.PATCH` tags.

## [Unreleased]

### Added

- Established the checked-in changelog and release gate.
- RFC-0008 daemon lifecycle across SSH, containers, nix-shell, tmux, sudo. Status: Draft. Gates further `src/daemon/server.zig` growth until accepted.
- Build option `-Dvcs_extra=true` re-enables the hg/jj/sl/stack/worktree CLI verbs and their test stanzas. Default off.
- `src/redact.zig` (formerly `src/ai/redact.zig`) retained as a generic privacy utility for `shisa report` and `zig build bench`.

### Changed

- North-star §1 leads with the falsifiable cold-render promise; §10 promotes the cold big-repo target above warm-p99 and names sub-millisecond warm as a non-target; §16 promotes daemon lifecycle to top risk; §17 adds SSH / container / nix-shell open questions.
- North-star §15 drops the 5K-stars criterion (no comms scope to back it); replaced with a reproducible-benchmark outcome.
- `docs/profiling.md` leads with the cold-big-repo headline target via `bench/compare-prompts.sh`. `zig build bench` reframed as a microbench harness with a `headline` key pointing at the hyperfine script.
- `todo.md` restructured as MVP-first with a READ-FIRST banner anchoring on north-star.

### Removed

- `src/ai/*.zig` (13 files) and AI CLI verbs (`shisa ai`). `docs/ai-*.md`, `docs/recipes/ai-hotkey-local-model.md`, and `prompts/` removed. Config `[ai]` section, `AiProviderId` enum, and `Ai` options removed from `src/config.zig`. Spec for the future opt-in AI pack retained in north-star §18; code recoverable from git history.
