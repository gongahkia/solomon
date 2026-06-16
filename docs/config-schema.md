# `shisa.toml` Schema

Shisa reads user config from `$XDG_CONFIG_HOME/shisa/shisa.toml`, falling back to `~/.config/shisa/shisa.toml`.

## Minimal File

```toml
version = 1
theme = "plain"

[prompt]
modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host", "sso_expiry", "iac_workspace", "region_drift"]
```

## Top-Level Keys

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `version` | integer | yes | none | Must be `1`. |
| `theme` | string | no | `"plain"` | Built-in theme id or absolute/tilde path to a theme TOML file. See `docs/theme-spec.md`. |

Unknown top-level keys are invalid.

## `[prompt]`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `modules` | array of strings | no | see below | Ordered left-prompt module pipeline. Values must be unique. |

Default module order:

```toml
[prompt]
modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host", "sso_expiry", "iac_workspace", "region_drift"]
```

Allowed core module ids for schema v1:

| Module | Execution | Summary |
| --- | --- | --- |
| `cwd` | sync | Current directory, home-tilde, truncation. |
| `git_branch` | async | Git branch name and dirty marker. |
| `language_versions` | async | Python, Node, Rust, and Go versions for detected projects. |
| `exit_status` | sync | Non-zero exit code segment. |
| `jobs` | sync | Background job count. |
| `cmd_duration` | sync | Last command duration above threshold. |
| `user_host` | sync | User and host, normally only over SSH. |
| `cloud_ctx` | sync | Optional cloud account context; AWS profile, cached GCP project, cached Azure subscription, and cached Kubernetes context support are available. |
| `risk_tier` | sync | Risk classification and prompt background-bar color mapping. |
| `sso_expiry` | sync | Warn when cached SSO/session expiry metadata is below the configured threshold. |
| `iac_workspace` | sync | Render local Terraform/OpenTofu/Pulumi/CDK workspace metadata. |
| `region_drift` | sync | Warn when region env vars differ from provider config defaults. |
| `time` | sync | Optional UTC `HH:MM` clock segment. |

Unknown module ids are invalid.

## Per-Module Options

Per-module config lives under `[modules.<id>]`. Option tables may exist only for known module ids.

### `[modules.cwd]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `truncate_to` | integer | `3` | `0..16`; `0` disables truncation. |
| `home_tilde` | bool | `true` | Replace `$HOME` prefix with `~`. |

### `[modules.git_branch]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `show_dirty` | bool | `true` | Append `*` when worktree is dirty. |
| `cache_ttl_ms` | integer | `250` | `0..60000`; `0` means no TTL reuse. |

### `[modules.language_versions]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `detect` | array of strings | `["python", "node", "rust", "go"]` | Schema v1 recognizes these four values. |

### `[modules.exit_status]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `show_zero` | bool | `false` | Show `exit:0` when true. |

### `[modules.jobs]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `show_zero` | bool | `false` | Show `jobs:0` when true. |

### `[modules.cmd_duration]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `threshold_ms` | integer | `1000` | `0..86400000`. |

### `[modules.user_host]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `mode` | string | `"ssh"` | One of `"ssh"`, `"always"`, `"never"`. |

### `[modules.cloud_ctx]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `aws` | bool | `true` | Show AWS profile context. |
| `gcp` | bool | `true` | Show GCP project context. |
| `azure` | bool | `true` | Show Azure subscription context. |
| `kubernetes` | bool | `true` | Show Kubernetes context and namespace. |

AWS profile is resolved from `AWS_PROFILE`; when unset, Shisa reads `~/.aws/config` and uses `[default]` or the first `[profile <name>]` section. GCP project is cached from the active Cloud SDK config file under `~/.config/gcloud/configurations/` and invalidated when `~/.config/gcloud/` changes. Azure subscription is cached from `~/.azure/azureProfile.json` and invalidated when that file changes. Kubernetes context is cached from the first `KUBECONFIG` path, or `~/.kube/config`, and invalidated when that file changes. Multiple providers render in one `cloud[...]` segment with ASCII provider markers: `aws`, `gcp`, `az`, and `k8s`.

### `[modules.risk_tier]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `unknown_bg` | string | `"muted"` | One of `"fg"`, `"muted"`, `"accent"`, `"success"`, `"warning"`, `"danger"`. |
| `dev_bg` | string | `"success"` | Same as `unknown_bg`. |
| `staging_bg` | string | `"warning"` | Same as `unknown_bg`. |
| `prod_bg` | string | `"danger"` | Same as `unknown_bg`. |

These map risk tiers to prompt background-bar palette slots. Rule matching defaults and user-rule file format are documented in `docs/risk-tiers.md`.

### `[modules.sso_expiry]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `warning_minutes` | integer | `30` | `1..1440`. |

Reads cached token expiry metadata only. Sources are documented in `docs/sso-expiry.md`.

### `[modules.time]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `format` | string | `"24h"` | Only `"24h"` in schema v1. |
| `utc` | bool | `true` | Must be `true` until local timezone support lands. |

## Validation Rules

- `version` must be present and equal to `1`.
- `[prompt].modules` must be an array of unique strings.
- Each module in `[prompt].modules` must be a known core module id or a loaded plugin module id.
- `[modules.<id>]` must reference a known module id.
- Unknown keys in known tables are invalid.
- Type mismatch, range violation, duplicate module id, and unknown module id errors must include file, line, and column.
