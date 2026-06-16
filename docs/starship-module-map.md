# Starship Module Map

This map covers the first 30 Starship modules Shisa treats during import planning. Source module names follow Starship's configuration docs: https://starship.rs/config/

| Starship module | Shisa target | Import status | Notes |
| --- | --- | --- | --- |
| `directory` | `cwd` | supported | Directory truncation becomes Shisa cwd defaults. |
| `git_branch` | `git_branch` | supported | Branch name maps directly. |
| `git_status` | `git_branch` | partial | Shisa currently renders a dirty marker, not every Starship status symbol. |
| `git_commit` | `git_branch` | partial | Detached commit hash is not preserved. |
| `git_state` | `git_branch` | partial | Rebase/merge state text is not preserved. |
| `cmd_duration` | `cmd_duration` | supported | Threshold options are not imported yet. |
| `status` | `exit_status` | supported | Non-zero code maps directly. |
| `jobs` | `jobs` | supported | Running job count maps directly. |
| `username` | `user_host` | supported | Combined with hostname in Shisa. |
| `hostname` | `user_host` | supported | Combined with username in Shisa. |
| `time` | `time` | supported | Imported as UTC 24h until local time lands. |
| `python` | `language_versions` | supported | Enables Python detection. |
| `nodejs` | `language_versions` | supported | Enables Node detection. |
| `rust` | `language_versions` | supported | Enables Rust detection. |
| `golang` | `language_versions` | supported | Enables Go detection. |
| `java` | none | unsupported | Planned as a future language detector. |
| `package` | none | unsupported | No package-version core module yet. |
| `docker_context` | none | unsupported | Planned for cloud/container plugin pack. |
| `kubernetes` | none | unsupported | Covered by reference Lua plugin, not core import output. |
| `aws` | none | unsupported | Covered by reference Lua plugin, not core import output. |
| `gcloud` | none | unsupported | Planned cloud plugin. |
| `azure` | none | unsupported | Planned cloud plugin. |
| `nix_shell` | none | unsupported | Planned environment module. |
| `env_var` | none | unsupported | Requires explicit config translation. |
| `custom` | none | unsupported | Arbitrary commands are not imported for safety. |
| `character` | shell hook | ignored | Shisa shell hooks own final prompt marker. |
| `line_break` | shell hook | ignored | Shisa emits a single prompt line. |
| `fill` | layout | ignored | Right-fill layout is not implemented yet. |
| `shell` | shell hook | ignored | Shell identity is request metadata. |
| `os` | none | ignored | OS glyph styling belongs in themes or plugins. |

Unsupported modules are emitted as comments by `shisa import-starship`. Ignored modules are intentionally omitted because Shisa owns that behavior elsewhere.
