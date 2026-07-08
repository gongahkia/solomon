# `shisa.toml` Schema

Generated from `src/config.zig` with `zig build config-schema-docs`.

Shisa reads user config from `$XDG_CONFIG_HOME/shisa/shisa.toml`, falling back to `~/.config/shisa/shisa.toml`.

## Minimal File

```toml
version = 1
theme = "plain"
locale = "auto"

[prompt]
modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host", "risk_tier", "sso_expiry", "iac_workspace", "region_drift", "cost_glance", "vpn_status", "ssh_target", "container_provenance"]
right_modules = []
rtl_reverse = false

[ai]
provider = "ollama"
```

## Top-Level Keys

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `version` | integer | yes | none | Must be `1`. |
| `theme` | string | no | `"plain"` | Built-in theme id or absolute/tilde path to a theme TOML file. See `docs/theme-spec.md`. |
| `locale` | string | no | `"auto"` | `auto` uses shell locale detection; otherwise a BCP 47-ish locale such as `en-US` or `ar-EG`. |

Unknown top-level keys are invalid.

## `[prompt]`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `modules` | array of strings | no | see below | Ordered left-prompt module pipeline. Values must be unique. |
| `right_modules` | array of strings | no | `[]` | Ordered right-prompt module pipeline for shells with native right prompt support. Values must be unique. |
| `rtl_reverse` | bool | no | `false` | Reverse rendered segment order only when the session is detected as RTL. |

Default module order:

```toml
[prompt]
modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host", "risk_tier", "sso_expiry", "iac_workspace", "region_drift", "cost_glance", "vpn_status", "ssh_target", "container_provenance"]
right_modules = []
rtl_reverse = false
```

## `[ai]`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `provider` | string | no | `"ollama"` | One of `"ollama"`, `"openai"`, `"anthropic"`, `"gemini"`, `"lmstudio"`, or `"llamacpp"`. |
| `model` | string | no | provider default | Default model or local model path for AI commands. Explicit `--model` wins. |
| `plugin` | string | only for configured cloud providers | none | Plugin id whose `net=<provider>` trust grant authorizes config-selected cloud providers. |

`[ai]` defaults apply to `shisa ai risk`, `explain`, `nextcmd`, and `nl2cmd`. Explicit CLI flags override config. Config-selected cloud providers require `shisa plugin trust <plugin> --net=<provider>`.

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
| `cloud_ctx` | sync | Optional cloud account context; AWS, GCP, Azure, and Kubernetes support are available. |
| `cdhint` | sync | Compact local project kind hint from marker files. |
| `tmux_pane` | sync | Render the current tmux pane id from `TMUX_PANE`. |
| `risk_tier` | sync | Risk classification and prompt background-bar color mapping. |
| `sso_expiry` | sync | Warn when cached SSO/session expiry metadata is below the configured threshold. |
| `iac_workspace` | sync | Render local Terraform/OpenTofu/Pulumi/CDK workspace metadata. |
| `region_drift` | sync | Warn when region env vars differ from provider config defaults. |
| `cost_glance` | sync | Render compact month-to-date cloud spend from the local cost cache. |
| `vpn_status` | sync | Render active local VPN status from local client commands. |
| `ssh_target` | sync | Render remote SSH target host and risk tier. |
| `container_provenance` | sync | Render detected container/runtime provenance. |
| `time` | sync | Optional UTC `HH:MM` clock segment. |

Unknown module ids are invalid.

## Per-Module Options

Per-module config lives under `[modules.<id>]`. Option tables may exist only for known module ids.

### `[modules.cwd]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `truncate_to` | integer | `3` | `0..16`; `0` disables truncation. |
| `home_tilde` | bool | `true` | Replace `$HOME` prefix with `~`. |
| `max_width` | integer | `0` | `0..512`; `0` disables display-width truncation. |

### `[modules.git_branch]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `show_dirty` | bool | `true` | Append `*` when worktree is dirty. |
| `cache_ttl_ms` | integer | `250` | `0..60000`; `0` means no TTL reuse. |

### `[modules.language_versions]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `detect` | array of strings | `["python", "node", "rust", "go"]` | Schema v1 recognizes these four values. |
| `path_hash_invalidate` | bool | `false` | Opt-in. Include a SHA-256 hash of `$PATH` plus the active PATH in render requests so the daemon can invalidate and probe the correct toolchain. |

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

### `[modules.cdhint]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Disable cdhint rendering when false. |

Place `.shisa-no-cdhint` in the current directory or detected project tree to suppress local cd hints for that tree.

### `[modules.tmux_pane]`

| Key | Type | Default | Constraints |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Disable tmux pane rendering when false. |

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
- `[prompt].right_modules` must be an array of unique strings.
- `[ai].provider` must be a known AI provider id.
- Config-selected cloud AI providers require `[ai].plugin` and a matching plugin net trust grant.
- Each module in `[prompt].modules` and `[prompt].right_modules` must be a known core module id or a loaded plugin module id.
- `[modules.<id>]` must reference a known module id.
- Unknown keys in known tables are invalid.
- Type mismatch, range violation, duplicate module id, and unknown module id errors must include file, line, and column.
