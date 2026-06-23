# Bench Results

Local host: `Mac15,12`, Apple M3, macOS 26.5.1. Date: 2026-06-23.

## Prompt comparison

`bench/compare-prompts.sh` with Starship 1.25.1, Oh My Posh 29.17.0, and Powerlevel10k 1.20.0:

- Shisa: 1.7 ms mean
- Starship: 9.6 ms mean
- Oh My Posh: 14.5 ms mean
- p10k: 147.6 ms mean

Artifacts: `comparison.json`, `comparison.md`.

## VCS Starship-Git

`bench/vcs-starship-git.sh` generated clean, dirty, and linked-worktree Git fixtures:

- Shisa: 1.9-2.0 ms mean
- Starship: 9.9-11.1 ms mean

Artifacts: `vcs-starship-git.json`, `vcs-starship-git.md`.

## nixpkgs

Fixture: blobless depth-1 clone of `NixOS/nixpkgs`, commit `8986399b3`, 52,993 checked-out files, 399 MiB temporary working tree at `/tmp/shisa-nixpkgs-bench` (removed after the run).

- Cold: fresh daemon per sample, 10 runs, mean 69.8 ms, min 33.8 ms, max 103.7 ms.
- Warm: one daemon, warmed prompt path, 50 runs, mean 21.6 ms, min 19.7 ms, max 36.2 ms.

Artifacts: `nixpkgs-cold.json`, `nixpkgs-cold.md`, `nixpkgs-warm.json`, `nixpkgs-warm.md`.

## Chromium sparse

Fixture: blobless depth-1 sparse root clone of `chromium/src`, commit `dd0350b6`, 36 checked-out files, 100 MiB temporary working tree at `/tmp/shisa-chromium-bench` (removed after the run). This is not a substitute for a full Chromium checkout; no local full clone was present and the machine had 65-66 GiB free, which is not enough safe headroom for a real checkout.

- Cold: fresh daemon per sample, 10 runs, mean 30.6 ms, min 23.0 ms, max 36.1 ms.
- Warm: one daemon, warmed prompt path, 50 runs, mean 1.9 ms, min 1.7 ms, max 2.2 ms.

Artifacts: `chromium-sparse-cold.json`, `chromium-sparse-cold.md`, `chromium-sparse-warm.json`, `chromium-sparse-warm.md`.

## Git advanced 1M

Fixture: generated Git repo with 1,000,000 commits, upstream set to `ahead=1 behind=0`, one staged file, one unstaged tracked file, one untracked file, and a 289 MiB temporary working tree at `/tmp/shisa-git-advanced-1m` (removed after the run). The benchmark strips `PATH` for Shisa/shisad, so spawned `git` cannot satisfy the prompt; this verifies the runtime-loaded libgit2 path.

- Cold: fresh daemon inside the measured command, 10 runs, mean 264.9 ms, min 259.9 ms, max 269.9 ms.
- Warm: one daemon, warmed prompt path, 50 runs, mean 8.0 ms, min 5.1 ms, max 30.0 ms.

Artifacts: `git-advanced-1m-cold.json`, `git-advanced-1m-cold.md`, `git-advanced-1m-warm.json`, `git-advanced-1m-warm.md`.

## Terminal async redraw

Plain zsh/tmux passed through existing integration tests. Alacritty 0.17.0 was tested from a checksum-verified upstream DMG because the Homebrew cask is Gatekeeper-deprecated and produced a broken `/Applications/Alacritty.app` symlink on this host. iTerm 3.6.11 was tested through AppleScript. Both app sessions verified `SHISA_ASYNC_FD`, FIFO creation, and `USR1` notification markers from inside interactive zsh.
