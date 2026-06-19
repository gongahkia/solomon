# Shisa - Active TODO

Status legend: `[ ]` open.

Removed scope: launch/comms, external audits/compliance, hosted docs publishing, branding/swag, social/community ops, and release publicity.

## Packaging and supply chain

- [ ] Author Homebrew formula (tap first; homebrew-core only if later needed)
- [ ] Author Scoop manifest for WSL users
- [ ] Author Flatpak manifest if desktop packaging remains in scope
- [ ] Author Snap manifest if snap packaging remains in scope
- [ ] Set up macOS code signing and notarization for distributed artifacts
- [ ] Implement `shisa update` release-metadata check as an opt-in network call
- [ ] Implement Sigstore verification for self-update artifacts
- [ ] Implement `shisa update --verify` before applying updates
- [ ] Implement atomic self-update swap with rollback on failure

## Validation and performance

- [ ] Run prompt benchmarks on nixpkgs and chromium clones; record cold and warm numbers
- [ ] Run comparison benchmark vs starship, p10k, and oh-my-posh for package candidates
- [ ] Verify Linux Wayland-only behavior
- [ ] Test under systemd-nspawn, podman, and distrobox
- [ ] Test under nix-shell, devenv, and flox PATH/language-version environments
- [ ] Build full-OS Docker E2E images for supported distros
- [ ] Run shells inside E2E containers and assert prompt output
- [ ] Maintain `shell x distro x version` E2E matrix
- [ ] Run one documented hardware performance baseline before packaging
- [ ] Test zsh async redraw in tmux, plain zsh, Alacritty, and iTerm
- [ ] Bench `nextcmd` median round-trip under 800ms on a 2020 MacBook Air
- [ ] Benchmark advanced git states on a 1M-commit repo

## Plugin marketplace

- [ ] Stand up plugin marketplace index in-repo without hosted-site dependency
- [ ] Seed marketplace with vetted community plugin entries
- [ ] Link community-tier VCS templates from the marketplace index
- [ ] Add marketplace entry validation to CI
- [ ] Document marketplace index format in local repo docs

## Local repo docs

- [ ] Keep `README.md` as the canonical public overview
- [ ] Keep local repo docs aligned with packaging, update, marketplace, and feature changes
- [ ] Remove stale hosted publishing references when touched

## Feature actionables

- [ ] Hook `errfix` into last command stderr capture
- [ ] On non-zero exit, surface a one-line `shisa: try <x>?` hint
- [ ] Add per-exit user opt-in for `errfix` hints
- [ ] Index shell history into a local vector store
- [ ] Add hotkey for fuzzy semantic history search
- [ ] Add optional atuin sqlite adapter for semantic history search
- [ ] Use libgit2 bindings via Zig FFI for advanced git states
- [ ] Extract all user-facing strings to the gettext catalog
