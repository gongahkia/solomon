# Powerlevel10k Module Map

This table covers the first Powerlevel10k elements Shisa imports from `POWERLEVEL9K_LEFT_PROMPT_ELEMENTS` and `POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS`.

| Powerlevel10k element | Shisa module | Status | Notes |
| --- | --- | --- | --- |
| `dir` | `cwd` | supported | Directory shortening options are not imported yet. |
| `vcs` | `git_branch` | supported | Dirty/detail formatting is Shisa-owned. |
| `status` | `exit_status` | supported | Maps command status only. |
| `background_jobs` | `jobs` | supported | Maps job count. |
| `command_execution_time` | `cmd_duration` | supported | Threshold styling is not imported yet. |
| `context` | `user_host` | supported | Shisa renders according to `user_host` mode. |
| `time` | `time` | supported | Format options are not imported yet. |
| `aws` | `cloud_ctx` | supported | Uses Shisa cloud context detection. |
| `gcloud` | `cloud_ctx` | supported | Uses Shisa cloud context detection. |
| `azure` | `cloud_ctx` | supported | Uses Shisa cloud context detection. |
| `kubecontext` | `cloud_ctx` | supported | Uses Shisa Kubernetes context detection. |
| `virtualenv` | `language_versions` | supported | Enables Python detection. |
| `pyenv` | `language_versions` | supported | Enables Python detection. |
| `nodeenv` | `language_versions` | supported | Enables Node detection. |
| `nodenv` | `language_versions` | supported | Enables Node detection. |
| `nvm` | `language_versions` | supported | Enables Node detection. |
| `goenv` | `language_versions` | supported | Enables Go detection. |
| `go_version` | `language_versions` | supported | Enables Go detection. |
| `rust_version` | `language_versions` | supported | Enables Rust detection. |
| `os_icon` | none | ignored | Shisa themes own prompt icons. |
| `prompt_char` | none | ignored | Shisa prompt character is theme-owned. |
| `newline` | none | ignored | Layout translation handles line breaks separately. |
| `public_ip` | none | unsupported | No core public-IP module. |
| `ip` | none | unsupported | No core local-IP module. |
| `battery` | none | unsupported | No core battery module. |
| `ram` | none | unsupported | No core RAM module. |
| `load` | none | unsupported | No core load-average module. |
| `todo` | none | unsupported | No core todo module. |

Unsupported elements are emitted as comments in generated config and written to `migration-notes.md` by `shisa import-p10k`.

## Instant Prompt

`POWERLEVEL9K_INSTANT_PROMPT=quiet` and `POWERLEVEL9K_INSTANT_PROMPT=verbose` map to `SHISA_INSTANT=1`.

`POWERLEVEL9K_INSTANT_PROMPT=off` maps to `SHISA_INSTANT=0`.

Shisa controls instant prompt through shell hook environment and `shisa prompt --instant`; schema v1 has no TOML key for it.
