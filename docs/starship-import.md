# Starship Import

`shisa import-starship <path>` reads a Starship TOML file and prints a best-effort `shisa.toml`.

Supported mappings:

| Starship | Shisa |
| --- | --- |
| `directory` | `cwd` |
| `git_branch`, `git_status`, `git_commit`, `git_state` | `git_branch` |
| `python`, `nodejs`, `rust`, `golang` | `language_versions` |
| `status` | `exit_status` |
| `jobs` | `jobs` |
| `cmd_duration` | `cmd_duration` |
| `username`, `hostname` | `user_host` |
| `time` | `time` |

The importer prefers the top-level `format` string. If no single-line `format` is present, it falls back to module table names.

Unsupported Starship modules are emitted as a comment at the end of the generated file.

See `docs/starship-module-map.md` for the top-30 module mapping and unsupported list.
