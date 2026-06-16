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
- `test/fixtures/jj/*` snapshot fixture repos cover deterministic parser/render output.
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
- Verified Sapling 0.2.20260522 does not accept `sl status --json`; official status docs list plain status output and options: https://sapling-scm.com/docs/commands/status/
