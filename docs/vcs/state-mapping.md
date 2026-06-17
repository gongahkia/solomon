# VCS State Mapping

This table maps Git prompt states to native concepts in jj, Sapling, and Mercurial. It is the contract for cross-VCS prompt labels and test fixtures.

Sources:

- Git pseudorefs: https://git-scm.com/docs/gitrevisions
- Git rebase modes: https://git-scm.com/docs/git-rebase
- Jujutsu conflicts: https://docs.jj-vcs.dev/latest/conflicts/
- Sapling rebase conflicts: https://sapling-scm.com/docs/commands/rebase/
- Sapling mutation history: https://sapling-scm.com/docs/introduction/differences-git/
- Mercurial history editing: https://book.mercurial-scm.org/read/changing-history.html

## Operation States

| Git state | Git evidence | jj concept | Sapling concept | Mercurial concept |
| --- | --- | --- | --- | --- |
| rebase | `rebase-merge/`, `rebase-apply/`, or `REBASE_HEAD` | no suspended operation; conflicts live in commits | `sl rebase` conflict state and mutation history | rebase extension state |
| interactive rebase | `rebase-merge/interactive` or rebase todo | no direct equivalent; use operation log description | histedit-style stack rewrite | histedit extension state |
| merge | `MERGE_HEAD` | merge commit/change, possibly conflicted | merge in progress or conflicted changes | merge state / unresolved merge |
| cherry-pick | `CHERRY_PICK_HEAD` or sequencer todo | no direct sequencer; copied change plus op log | graft-like copied changes | graft / transplant-like operation |
| revert | `REVERT_HEAD` or sequencer todo | backed-out change plus op log | backout-like mutation | backout state when interrupted |
| bisect | `BISECT_HEAD` or bisect refs/log | no direct equivalent | no direct equivalent | no direct equivalent |
| am | `rebase-apply/` with mail patch state | no direct equivalent | import/apply patch workflow | import/patch queue workflow |
| detached HEAD | `HEAD` points to an object id, not a branch ref | normal anonymous working-copy commit | bookmarkless or detached-like position | no active bookmark/topic on current changeset |

## Working-Tree States

| Git state | Git evidence | jj concept | Sapling concept | Mercurial concept |
| --- | --- | --- | --- | --- |
| staged count | index differs from `HEAD` | no staging area; working-copy change owns edits | no Git-style staging area | no Git-style staging area |
| unstaged count | worktree differs from index | working-copy change modified files | `sl status` modified/added/removed files | `hg status` modified/added/removed files |
| untracked count | `??` status entries | untracked files | `sl status` unknown files | `hg status` unknown files |
| conflict count | unmerged index entries | conflicted files recorded in commits | conflicted files in working copy/stack | unresolved merge conflicts |
| stash count | `refs/stash` reflog | no direct equivalent; use abandoned/op-log recovery | shelve-like workflow | shelve extension |
| sparse checkout | sparse-checkout config/index flags | no direct equivalent | sparse/profile features, if enabled | narrow clone, if enabled |
| submodule dirty | submodule status | Git-backed subrepo evidence only | Git submodule evidence only | subrepo status |
| LFS pointer state | `.gitattributes` plus pointer files | Git backend evidence only | Git/LFS backend evidence only | largefiles extension equivalent |

## Branch and Remote States

| Git state | Git evidence | jj concept | Sapling concept | Mercurial concept |
| --- | --- | --- | --- | --- |
| ahead/behind upstream | branch upstream merge-base counts | tracked remote bookmarks or Git backend refs | remote bookmark divergence | incoming/outgoing summary |
| last fetch age | remote-tracking ref mtimes / fetch metadata | operation log / Git backend fetch state | pull/fetch metadata | pull/update summary age |
| signed HEAD | commit signature check | Git-backed commit signature where present | Git-backed commit signature where present | changeset signature extensions, if configured |
| branch protection | remote provider API/cache | provider-level concept only | provider-level concept only | provider-level concept only |

## Rendering Contract

- If a VCS has no native equivalent, render `n/a` only in diagnostic output; prompts should omit the segment.
- If a state exists but needs backend-specific evidence, prefix it with the backend, for example `git-lfs` or `provider`.
- Accessibility labels must spell out the operation, for example `rebase in progress`, not only show a glyph.
- Snapshot fixtures must include at least one positive and one absent case for each supported native state.
