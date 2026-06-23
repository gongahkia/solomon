# Profiling Notes

Use this page before changing prompt rendering, cache invalidation, VCS probing, shell hooks, or plugin host APIs.

## Headline target

**Cold prompt render in a real big repo, no timeout.** This is the falsifiable promise from north-star §10. Every other budget on this page is supporting evidence.

Evidence path: `bench/compare-prompts.sh` driven by `hyperfine` against a synthetic or real big repo (chromium, nixpkgs, or a 1M-commit fixture). The CI gate compares Shisa's cold render to starship's on the same fixture and fails the PR if the gap closes by more than 10%.

## Targets

| Target | Command | Evidence |
| --- | --- | --- |
| **Cold render in big repo** (headline) | `bench/compare-prompts.sh` | `bench-results/comparison.json` and `.md` from `hyperfine`. |
| VCS prompt comparison | `bench/vcs-starship-git.sh` | Shisa vs Starship on clean, dirty, and linked-worktree repos. |
| jj scale probe | `bench/jj-10k.sh` | jj command timings on a generated large history. |
| Core and pack microbench | `zig build bench` | JSON stdout: cloud-context cold/warm, protocol frame timing, pack budgets. Supporting only. |

## Fast-Path Budget

The warm prompt target is p99 under 2 ms — an **upper bound on the hot path**, not the marketing line. Below ~10 ms is sub-perceptual to humans; the cold-big-repo target above is the user-feelable win.

The shell hot path should only package state, call the daemon socket, print the returned prompt, or print the fallback prompt.

Do not add these to the shell hot path:

- subprocesses
- recursive filesystem walks
- network calls
- package manager calls
- blocking plugin work
- unbounded JSON or config parsing

Use async modules or daemon-maintained caches for slow work.

## Local Baseline

```sh
zig build test
zig build release
zig build bench
```

For end-to-end prompt timing:

```sh
bench/compare-prompts.sh
```

For VCS-specific timing:

```sh
bench/vcs-starship-git.sh
bench/jj-10k.sh
```

Keep benchmark outputs under `bench-results/` when comparing before/after changes. Do not commit ad-hoc result files unless the result itself is the deliverable.

## Isolating Prompt Work

Start a daemon on a temporary socket:

```sh
sock=/tmp/shisa-profile.sock
./zig-out/bin/shisad --foreground --socket "$sock"
```

Render the normal daemon-backed prompt:

```sh
./zig-out/bin/shisa prompt --socket "$sock" --cwd "$PWD" --shell zsh --cols 80 --rows 24
```

Render synchronous module paths for comparison:

```sh
./zig-out/bin/shisa prompt --socket "$sock" --cwd "$PWD" --shell zsh --cols 80 --rows 24 --no-async
```

Use `--no-async` only to isolate worst-case module cost. It is not the target interactive path.

## Reading Results

| Symptom | First check |
| --- | --- |
| Cold render is slow | config parse, cache warmup, first filesystem probe, first external command. |
| Warm render is slow | daemon render path, cache lookup, string allocation, protocol framing. |
| Dirty Git repo is slow | `git status --porcelain` cost and async cache invalidation. |
| Large jj repo is slow | `jj op log` and `jj log -r @` command time in `bench/jj-10k.sh`. |
| Shell feels slow but daemon is fast | hook duration capture, socket path checks, terminal redraw behavior. |
| CI regression only | compare runner OS, Zig version, `hyperfine` run count, and warmup count. |

## CI Gate

`.github/workflows/bench.yml` runs `shisa bench` on pull requests and compares p99 against `main`. A pull request fails when the measured p99 is more than 10% above the baseline.

The same workflow runs `zig build bench` on pull requests and every Monday at 03:17 UTC on `main`. That command fails when any pack-level budget in [Pack Status](pack-status.md) is exceeded.

The same workflow publishes a benchmark dashboard on pushes to `main`.

## Reporting

Attach:

- command used
- OS and shell
- Zig version
- repo size or fixture details
- warmup/run counts
- JSON output when available
- the commit range being compared

See [Architecture](architecture.md) and [VCS](vcs/index.md).
