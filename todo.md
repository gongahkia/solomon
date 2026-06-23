# Shisa — Active TODO

**READ FIRST:** [`north-star.md`](north-star.md) is the source of truth for Shisa's scope and ethos. Read it in full before adding or editing tasks here. If a task would contradict the north star, update the north star in the same change. This file is execution; that file is intent.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done.

## Phase-0 scope-cut + refocus (in progress)

Tracks the audit-driven refocus. One commit per task, easy `git revert` per row.

- [x] T1 — Rewrite `north-star.md` ethos pass (§1 headline, §3 AI contract, §10 cold-big-repo first, §16 lifecycle risk, §17 lifecycle questions, read-first banner)
- [x] T2 — Restructure this file as MVP-first, anchor to north-star
- [x] T3 — RFC-0008: daemon lifecycle in SSH / containers / nix-shell / tmux / sudo (blocks further dispatcher growth)
- [x] T4 — Delete `src/ai/` and related docs (spec retained in north-star §18; recoverable from git history)
- [x] T5 — Gate hg/jj/sl/stack/worktree behind `-Dvcs_extra=false` default
- [x] T6 — Reframe `shisa bench` to lead with cold-cache big-repo render
- [x] T7a — Extract `src/cli/theme.zig` from `main.zig`
- [ ] T7b — Extract `src/cli/config.zig` from `main.zig`
- [ ] T7c — Extract `src/cli/doctor.zig` from `main.zig`
- [ ] T7d — Extract `src/cli/plugin.zig` from `main.zig` (largest win, ~2.5K lines)
- [ ] T7e — Extract `src/cli/stack.zig` + `src/cli/worktree.zig` (gated by `-Dvcs_extra`)
- [x] T8 — Drop §15 5K-stars success criterion, replace with reproducible-benchmark outcome
- [x] T9 — Align README / architecture / quickstart / CHANGELOG with the gates and deletions

## Phase-0 re-audit follow-ups

Triggered after empirical verification: `shisad` boots, renders, async path works, warm p99 < 2 ms achievable. The "pre-MVP" README label understates state.

- [ ] T10 — Reality-check README "pre-MVP" status (working daemon-rendered prompt today; re-label as alpha + known-issues)
- [ ] T11 — Wire `bench/compare-prompts.sh` into CI on a representative big-repo fixture (verifies the headline)
- [ ] T12 — Add p99 assertion to `zig build bench`; characterize the 5 ms render outliers (3.5% > 5ms in the 56-run sample)
- [ ] T13 — Promote RFC-0008 from Draft to Accepted (or relax north-star §16 wording so the gate has teeth)
- [ ] T14 — CI guard: fail PRs that push any `src/daemon/*.zig` past 3000 lines
- [ ] T15 — Write `docs/internals/rfc-0008-daemon-lifecycle.md` decision summary (required by `scripts/rfc-internals-gate.sh` once RFC-0008 is Accepted)
- [ ] T16 — Finish T7b–e main.zig split (config / doctor / plugin / stack+worktree)
- [ ] T17 — *Needs user approval (destructive)*: squash or rewrite the two stray `adde`/`added` commits with descriptive messages
- [x] T18 — Freeze additions to plugin infrastructure (signing, marketplace validation, manifest CI) until ≥ 1 third-party plugin exists
- [ ] T19 — First-run smoke integration test: fresh `$HOME` → `shisa init` → source hook → assert working prompt
- [x] T20 — Read `docs/why-zig.md` and reconcile any claims against the empirical state

## MVP-blocking (phase 1: zsh + macOS + basic git)

Do these before any phase 2+ work. The MVP gate is: a working zsh-on-macOS prompt that beats starship on a cold render in nixpkgs.

- [ ] Land RFC-0008 (T3) before any further `src/daemon/server.zig` growth
- [ ] Bench `nextcmd` median round-trip under 800ms on a 2020 MacBook Air — **rewrite as a prompt-render bench, not AI** (AI removed in T4)
- [ ] Run prompt benchmarks on nixpkgs and chromium clones; record cold and warm numbers
- [ ] Run comparison benchmark vs starship, p10k, and oh-my-posh
- [ ] Test zsh async redraw in tmux, plain zsh, Alacritty, and iTerm
- [ ] Use libgit2 bindings via Zig FFI for advanced git states
- [ ] Benchmark advanced git states on a 1M-commit repo

## Hardening (phase 2-3)

- [ ] Verify Linux Wayland-only behavior
- [ ] Test under systemd-nspawn, podman, and distrobox
- [ ] Test under nix-shell, devenv, and flox PATH/language-version environments
- [ ] Build full-OS Docker E2E images for supported distros
- [ ] Run shells inside E2E containers and assert prompt output
- [ ] Maintain `shell x distro x version` E2E matrix
- [ ] Run one documented hardware performance baseline before packaging
- [ ] Hook `errfix` into last command stderr capture — **deferred to `shisa.ai` pack (phase 12); not core**
- [ ] On non-zero exit, surface a one-line `shisa: try <x>?` hint — same: deferred to phase 12
- [ ] Add per-exit user opt-in for `errfix` hints — same: deferred to phase 12
- [ ] Index shell history into a local vector store — same: deferred to phase 12
- [ ] Add hotkey for fuzzy semantic history search — same: deferred to phase 12
- [ ] Add optional atuin sqlite adapter for semantic history search — same: deferred to phase 12

## Packaging + supply chain (phase 7; do not work on until MVP ships)

- [ ] Author Homebrew formula (tap first; homebrew-core only if later needed)
- [ ] Author Scoop manifest for WSL users
- [ ] Author Flatpak manifest if desktop packaging remains in scope
- [ ] Author Snap manifest if snap packaging remains in scope
- [ ] Set up macOS code signing and notarization for distributed artifacts
- [ ] Implement `shisa update` release-metadata check as an opt-in network call
- [ ] Implement Sigstore verification for self-update artifacts
- [ ] Implement `shisa update --verify` before applying updates
- [ ] Implement atomic self-update swap with rollback on failure

## Deferred packs (phase 10-12; do not work on until MVP ships)

The packs in north-star §18–21 are deferred. No code or docs added under these headings before phase 1 ships. Listed here as a reminder, not an active worklist:

- `shisa.vcs` extras (jj/sapling/hg) — code exists, gated off in T5
- `shisa.cloud` (cloud_ctx, risk_tier, prod_guard, sso_expiry, iac_workspace, region_drift, cost_glance, vpn_status, ssh_target, container_provenance)
- `shisa.ai` (nextcmd, nl2cmd, explain, risk, errfix, histsearch, cdhint) — code deleted in T4; spec lives in north-star §18
- `shisa.activity` (long_running, cmd_complete_bell, tmux_pane, right_prompt)

## Plugin marketplace (phase 14; do not work on until MVP ships)

**Freeze** (T18): no further additions to plugin infrastructure (signing, marketplace validation, manifest CI) until ≥ 1 third-party plugin actually exists. Current `src/plugin/lua.zig` is 1090 lines and `plugins=0` in daemon metrics — the runtime is built ahead of any consumer. Phase-4 maintenance pressure should be deferred behind real-user signal.

- [ ] Stand up plugin marketplace index in-repo without hosted-site dependency
- [ ] Seed marketplace with vetted community plugin entries
- [ ] Link community-tier VCS templates from the marketplace index
- [ ] Add marketplace entry validation to CI
- [ ] Document marketplace index format in local repo docs

## Local repo docs

- [ ] Keep `README.md` as the canonical public overview
- [ ] Keep local repo docs aligned with packaging, update, marketplace, and feature changes
- [ ] Remove stale hosted publishing references when touched
- [ ] Extract all user-facing strings to the gettext catalog

## Cut from todo (with reason)

These were in this list and are now deliberately out of scope:

- Launch/comms, external audits/compliance, hosted docs publishing, branding/swag, social/community ops, release publicity — out of phase-0 scope. Reflected in T8 (§15 5K-stars criterion replaced with reproducible-benchmark outcome).
