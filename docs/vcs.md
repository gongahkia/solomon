# VCS Pack

`shisa.vcs` is incubating. Core helpers start with repository detection and fixture-backed parsing, then move to async prompt rendering.

## Jujutsu

Detection:

- Walk ancestors from `cwd`.
- A directory containing `.jj/` is the jj root.
- Detection does not require the `jj` binary.

Planned state sources:

- `.jj/op_heads` for fsnotify invalidation.
- `jj op log --no-graph` for operation summary.
- `jj log`/status output for current change, conflict state, and working-copy position.
