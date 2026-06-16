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
- `jj log --no-graph -r @` with a template for current change id, commit id, description first line, and divergence.
- `jj log --no-graph -r @` with `conflict` and `self.conflicted_files()` for inline conflict state.
- `jj log --no-graph -r @` with commit id and `parents.map()` for working-copy position.
