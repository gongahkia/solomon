# Tide Item Map

This table covers Tide prompt items from upstream preset config files: https://github.com/IlanCosman/tide/tree/main/functions/tide/configure/configs

| Tide item | Shisa target | Import status | Notes |
| --- | --- | --- | --- |
| `pwd` | `cwd` | supported | Directory rendering becomes Shisa cwd defaults. |
| `git` | `git_branch` | supported | VCS summary maps to Shisa VCS rendering. |
| `status` | `exit_status` | supported | Command status maps directly. |
| `cmd_duration` | `cmd_duration` | supported | Threshold options are imported in config mapping later. |
| `context` | `user_host` | supported | User/host maps to Shisa user_host behavior. |
| `jobs` | `jobs` | supported | Running job count maps directly. |
| `python` | `language_versions` | supported | Enables Python detection. |
| `node` | `language_versions` | supported | Enables Node detection. |
| `rustc` | `language_versions` | supported | Enables Rust detection. |
| `go` | `language_versions` | supported | Enables Go detection. |
| `aws` | `cloud_ctx` | supported | Uses Shisa AWS context detection. |
| `gcloud` | `cloud_ctx` | supported | Uses Shisa GCP context detection. |
| `kubectl` | `cloud_ctx` | supported | Uses Shisa Kubernetes context detection. |
| `terraform` | `iac_workspace` | supported | Uses Shisa IaC workspace detection. |
| `pulumi` | `iac_workspace` | supported | Uses Shisa IaC workspace detection. |
| `time` | `time` | supported | Imported as UTC 24h until local time lands. |
| `newline` | none | ignored | Shisa schema v1 emits a single prompt line. |
| `character` | none | ignored | Shisa shell hooks own final prompt marker. |
| `bun` | none | unsupported | No core Bun detector. |
| `java` | none | unsupported | No core Java detector. |
| `php` | none | unsupported | No core PHP detector. |
| `ruby` | none | unsupported | No core Ruby detector. |
| `crystal` | none | unsupported | No core Crystal detector. |
| `elixir` | none | unsupported | No core Elixir detector. |
| `zig` | none | unsupported | No core Zig detector. |
| `direnv` | none | unsupported | Environment state belongs in a plugin. |
| `distrobox` | none | unsupported | Container environment state is not imported yet. |
| `toolbox` | none | unsupported | Container environment state is not imported yet. |
| `nix_shell` | none | unsupported | Nix shell state is not imported yet. |

Items not listed above are unsupported unless a later importer row maps them explicitly.

## Fish-Specific Quirks

Tide is Fish-only and stores prompt state in `tide_*` Fish variables. The importer reads exported `tide_*` settings, not Tide functions or generated prompt functions.

- `tide_right_prompt_items` has no exact schema-v1 target while Shisa right prompt work is open, so items are mapped into the same module pipeline.
- `tide_left_prompt_frame_enabled`, `tide_right_prompt_frame_enabled`, separators, prefixes, and suffixes are layout/theme details; schema v1 does not preserve Tide's Powerline frame exactly.
- `tide_prompt_transient_enabled` is not imported because Shisa's Fish hook does not implement transient prompt replacement.
- Fish-local modes such as `vi_mode`, `private_mode`, and `shlvl` are unsupported unless represented by a mapped item.
- Tide colors can reference Fish variables such as `$_tide_color_green`; those require migration notes unless a later importer resolves Tide's private color variables.
