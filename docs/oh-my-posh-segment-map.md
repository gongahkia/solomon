# Oh My Posh Segment Map

This table covers the Oh My Posh segment enum used by `shisa import-oh-my-posh` planning. Source segment names follow the upstream schema: https://raw.githubusercontent.com/JanDeDobbeleer/oh-my-posh/main/themes/schema.json

| Oh My Posh segment | Shisa target | Import status | Notes |
| --- | --- | --- | --- |
| `path` | `cwd` | supported | Directory rendering becomes Shisa cwd defaults. |
| `git` | `git_branch` | supported | VCS branch/dirty summary maps to Shisa VCS rendering. |
| `jujutsu` | `git_branch` | partial | Shisa renders generic VCS summary through the git_branch module id. |
| `mercurial` | `git_branch` | partial | Shisa renders generic VCS summary through the git_branch module id. |
| `sapling` | `git_branch` | partial | Shisa renders generic VCS summary through the git_branch module id. |
| `svn` | `git_branch` | partial | Detailed SVN status is not preserved. |
| `fossil` | `git_branch` | partial | Detailed Fossil status is not preserved. |
| `plastic` | `git_branch` | partial | Detailed Plastic SCM status is not preserved. |
| `python` | `language_versions` | supported | Enables Python detection. |
| `node` | `language_versions` | supported | Enables Node detection. |
| `go` | `language_versions` | supported | Enables Go detection. |
| `rust` | `language_versions` | supported | Enables Rust detection. |
| `status` | `exit_status` | supported | Command status maps directly. |
| `executiontime` | `cmd_duration` | supported | Threshold options are not imported yet. |
| `session` | `user_host` | supported | User/host maps to Shisa user_host behavior. |
| `aws` | `cloud_ctx` | supported | Uses Shisa AWS context detection. |
| `gcp` | `cloud_ctx` | supported | Uses Shisa GCP context detection. |
| `az` | `cloud_ctx` | supported | Uses Shisa Azure context detection. |
| `kubectl` | `cloud_ctx` | supported | Uses Shisa Kubernetes context detection. |
| `terraform` | `iac_workspace` | supported | Uses Shisa IaC workspace detection. |
| `pulumi` | `iac_workspace` | supported | Uses Shisa IaC workspace detection. |
| `time` | `time` | supported | Imported as UTC 24h until local time lands. |
| `text` | none | ignored | Static separators are not imported as modules. |
| `shell` | none | ignored | Shell identity is request metadata. |
| `os` | none | ignored | OS glyph styling belongs in themes. |
| `upgrade` | none | ignored | Upgrade notifier is outside prompt rendering. |
| `battery` | none | unsupported | No core battery module. |
| `docker` | none | unsupported | Docker context is not the same as Shisa container provenance. |
| `ipify` | none | unsupported | No core public-IP module. |
| `sysinfo` | none | unsupported | No core CPU/RAM module. |
| `project` | none | unsupported | No package/project metadata core module yet. |
| `http` | none | unsupported | Network calls are not imported into prompt hot path. |
| `spotify` | none | unsupported | Media status belongs in a plugin. |
| `wakatime` | none | unsupported | External service calls belong in a plugin. |
| `taskwarrior` | none | unsupported | Task manager integrations belong in a plugin. |
Segments not listed above are unsupported unless a later importer row maps them explicitly.
