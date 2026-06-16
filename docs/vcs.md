# VCS Pack

`shisa.vcs` is incubating. Core helpers start with repository detection and fixture-backed parsing, then move to async prompt rendering.

## Jujutsu

Detection:

- Walk ancestors from `cwd`.
- A directory containing `.jj/` is the jj root.
- Detection does not require the `jj` binary.

Planned state sources:

- `.jj/repo/op_heads` for fsnotify invalidation on current jj releases.
- `jj op log --no-graph` for operation summary; Shisa parses the latest operation id and description.
- Async op-log rendering returns a pending state on cache misses, then refreshes cached output after `.jj/repo/op_heads` invalidation.
- `jj log --no-graph -r @` with a template for current change id, commit id, description first line, and divergence.
- `jj log --no-graph -r @` with `conflict` and `self.conflicted_files()` for inline conflict state.
- `jj log --no-graph -r @` with commit id and `parents.map()` for working-copy position.
- `test/fixtures/vcs/jj/*` snapshot fixture repos cover deterministic parser/render output.
- `bench/jj-10k.sh` benchmarks the jj commands Shisa wraps on a 10k-change imported repo.

## Sapling

Detection:

- Walk ancestors from `cwd`.
- A directory containing `.sl/` is the Sapling root.
- Detection does not require the `sl` binary.

State sources:

- `.sl/store` for fsnotify invalidation.
- `sl status --root-relative` for working-copy status counts.
- `sl log -r . --template` plus `sl log -r '::. - public()'` for current smartlog stack position.
- `sl log -r . --template '{branch}\n{activebookmark}\n'` for branch and active bookmark.
- `test/fixtures/vcs/sl/*` snapshot fixture repos cover deterministic parser/render output.
- Verified Sapling 0.2.20260522 does not accept `sl status --json`; official status docs list plain status output and options: https://sapling-scm.com/docs/commands/status/

## Mercurial

Detection:

- Walk ancestors from `cwd`.
- A directory containing `.hg/` is the Mercurial root.
- Detection does not require the `hg` binary.

State sources:

- `hg summary --remote` for parent, branch, commit/update state, and phases.
- When no default remote exists, Mercurial 7.2.2 exits 255 but still emits useful summary stdout; Shisa parses that stdout.
- `hg log -r . --template` for branch, active bookmark, current changeset phase, and `topic` extra when present.
- `hg --config extensions.mq= qqueue/qapplied/qseries` for active MQ queue, applied count, series count, and top patch; the empty default queue is suppressed.

## Stack Awareness

Detection:

- Walk ancestors from `cwd`.
- A directory containing `.graphite_repo_config` is treated as a Graphite stack root.
- Graphite detection does not require the `gt` binary.
- ghstack detection matches branch names shaped like `gh/<username>/<number>/{base,head,orig}` and explicit local `.ghstackrc` markers.
- Upstream ghstack documents submitted branch names as `gh/username/1/base`, `gh/username/1/head`, and `gh/username/1/orig`: https://github.com/ezyang/ghstack
- spr/git-spr detection checks `.git/refs/spr/` without requiring the `spr` binary.
- st/stax detection checks `.git/refs/branch-metadata/`, `.git/refs/stax/`, and repo-root `stax.toml`.
- stax upstream stores branch metadata under `refs/branch-metadata/` and documents repo-root `stax.toml` overlays: https://github.com/cesarferreira/stax
- git-spice detection checks `.git/refs/spice/data`, `.git/refs/spice/`, and packed refs for `refs/spice/data`.
- git-spice internals document local storage in `refs/spice/data`: https://abhinav.github.io/git-spice/guide/internals/
- git-town detection checks legacy `.git-town-branches.yml`, current `git-town.toml` / `.git-town.toml` / `.git-branches.toml`, and local Git config `git-town` entries.
- Git Town 22.7 documents config files named `git-town.toml`, `.git-town.toml`, or `.git-branches.toml`: https://www.git-town.com/configuration-file.html
- GitHub `gh stack` detection checks `.git/gh-stack`, `.git/gh-stack-rebase-state`, and GitHub remotes with stack metadata keys in `.git/config`.
- GitHub `gh stack` documents local tracking in `.git/gh-stack` and rebase state in `.git/gh-stack-rebase-state`: https://github.com/github/gh-stack
- Stack position rendering uses provider-prefixed segments like `stack:gh-stack:2/5 ↑↓`.
- `gh stack view --json` exposes `currentBranch` plus ordered `branches[]` with `isCurrent`; Shisa parses those fields for GitHub stack positions.
- `shisa stack [--cwd PATH]` prints the detected provider, root, marker, and branch evidence when available.

## Worktrees

Detection:

- Linked Git worktree detection reads a `.git` file that points at `.git/worktrees/<id>`.
- Primary worktrees with a `.git/` directory are not labeled as linked worktrees.
- Prompt rendering appends `wt:<name>` to the Git segment when `cwd` is inside a linked worktree.
- `shisa worktrees [--cwd PATH]` lists Git worktrees from `git worktree list --porcelain` and marks the active worktree with `*`.
- `shisa worktrees` runs `git status --porcelain` for each listed worktree and appends `*` to dirty worktree branch/status text.
