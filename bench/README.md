# Prompt Comparison Harness

Run:

```sh
bench/compare-prompts.sh
```

The harness builds Shisa, starts a temporary `shisad`, then benchmarks prompt render commands with `hyperfine`.

Outputs:

- `bench-results/comparison.json`
- `bench-results/comparison.md`

Targets:

- `shisa`: always included.
- `starship`: included when `starship` is in `PATH`.
- `oh-my-posh`: included when `oh-my-posh` is in `PATH`; set `OMP_CONFIG=/path/to/theme.omp.json` to pick a config.
- `p10k`: set `P10K_BENCH_CMD` to a noninteractive render command.

Tuning:

- `SHISA_BENCH_RUNS=50`
- `SHISA_BENCH_WARMUP=10`

## jj 10k-Change Harness

Run:

```sh
bench/jj-10k.sh
```

The harness creates a temporary Git history with 10,000 commits, imports it into jj, places `@` on top of `main`, and times the jj commands used by `shisa.vcs`.

Outputs:

- `bench-results/jj-10k.json`
- `bench-results/jj-10k.md`

Tuning:

- `SHISA_JJ_BENCH_CHANGES=20000`
- `SHISA_JJ_BENCH_RUNS=50`
- `SHISA_JJ_BENCH_KEEP_REPO=1`

## VCS Starship-Git Harness

Run:

```sh
bench/vcs-starship-git.sh
```

The harness creates clean, dirty, and linked-worktree Git repos, then benchmarks Shisa and Starship prompt rendering against the same repo paths.

Outputs:

- `bench-results/vcs-starship-git.json`
- `bench-results/vcs-starship-git.md`

Requirements:

- `git`
- `hyperfine`
- `starship`
- `zig`

Tuning:

- `SHISA_VCS_BENCH_RUNS=50`
- `SHISA_VCS_BENCH_WARMUP=10`
- `SHISA_VCS_BENCH_KEEP_REPOS=1`

## Git Advanced 1M Harness

Run:

```sh
bench/git-advanced-1m.sh
```

The harness creates or reuses a 1,000,000-commit Git repo, configures upstream ahead/behind state, leaves staged/unstaged/untracked files, strips `PATH` for Shisa/shisad so spawned `git` cannot satisfy the prompt, then benchmarks the libgit2-backed sync prompt path.

Outputs:

- `bench-results/git-advanced-1m-cold.json`
- `bench-results/git-advanced-1m-cold.md`
- `bench-results/git-advanced-1m-warm.json`
- `bench-results/git-advanced-1m-warm.md`

Tuning:

- `SHISA_GIT_1M_COMMITS=1000000`
- `SHISA_GIT_1M_COLD_RUNS=10`
- `SHISA_GIT_1M_WARM_RUNS=50`
- `SHISA_GIT_1M_KEEP_REPO=1`
