# `shisa.toml` Schema

Generated from `src/config.zig` with `zig build config-schema-docs`.

Shisa reads user config from `$XDG_CONFIG_HOME/shisa/shisa.toml`, falling back to `~/.config/shisa/shisa.toml`.

## Minimal File

```toml
version = 1
theme = "plain"
locale = "auto"

[prompt]
modules = ["cwd", "git_branch", "exit_status", "jobs", "cmd_duration", "user_host"]
right_modules = []
rtl_reverse = false
command_context = "off"
command_context_commands = ["aws", "az", "gcloud", "helm", "kubectl", "terraform", "tofu"]
command_context_modules = ["cloud_ctx", "risk_tier", "sso_expiry"]
```

## Top-Level Keys

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `version` | integer | yes | none | Must be `1`. |
| `theme` | string | no | `"plain"` | Built-in theme id or absolute/tilde path to a theme TOML file. See `docs/theme-spec.md`. |
| `locale` | string | no | `"auto"` | `auto` uses shell locale detection; otherwise a BCP 47-ish locale such as `en-US` or `ar-EG`. |
| `transient_prompt` | string | no | none | Compact prompt format for accepted lines. Supports `%~` for cwd with home tilde, `%d` for raw cwd, and `%%` for a literal percent. |

Unknown top-level keys are invalid.

## `[prompt]`

| Key | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `modules` | array of strings | no | see below | Ordered left-prompt module pipeline. Values must be unique. |
| `right_modules` | array of strings | no | `[]` | Ordered right-prompt module pipeline for shells with native right prompt support. Values must be unique. |
| `rtl_reverse` | bool | no | `false` | Reverse rendered segment order only when the session is detected as RTL. |
| `command_context` | string | no | `"off"` | Opt-in zsh command-aware target: `"off"`, `"right"`, or `"message"`. |
| `command_context_commands` | array of strings | no | see below | Executable names that trigger command-aware context. |
| `command_context_modules` | array of strings | no | see below | Modules rendered for a matching command. |

Default module order:

```toml
[prompt]
modules = ["cwd", "git_branch", "exit_status", "jobs", "cmd_duration", "user_host"]
right_modules = []
rtl_reverse = false
command_context = "off"
command_context_commands = ["aws", "az", "gcloud", "helm", "kubectl", "terraform", "tofu"]
command_context_modules = ["cloud_ctx", "risk_tier", "sso_expiry"]
```

Command-aware context is disabled by default. zsh debounces command-buffer updates, asks the daemon to render only the configured modules, and displays the result on the selected target. It never evaluates the command line; quoted, piped, redirected, or compound commands do not trigger context. `"right"` and `"message"` are currently implemented in zsh only.

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
| `cloud_ctx` | sync | Experimental cloud account context; AWS, GCP, Azure, and Kubernetes support. |
| `cdhint` | sync | Experimental compact local project-kind hint from marker files. |
| `tmux_pane` | sync | Experimental current tmux pane id from `TMUX_PANE`. |
| `risk_tier` | sync | Experimental risk classification and prompt background-bar mapping. |
| `sso_expiry` | sync | Experimental cached SSO/session-expiry warning. |
| `iac_workspace` | sync | Experimental Terraform/OpenTofu/Pulumi/CDK workspace metadata. |
| `region_drift` | sync | Experimental provider-region drift warning. |
| `cost_glance` | sync | Experimental compact local cloud-spend cache display. |
| `vpn_status` | sync | Experimental active local VPN status. |
| `ssh_target` | sync | Experimental remote SSH target and risk tier. |
| `container_provenance` | sync | Experimental container/runtime provenance. |
| `time` | sync | Optional UTC `HH:MM` clock segment. |

Unknown module ids are invalid.

## Plugin Configuration

Plugin settings are namespaced by loaded plugin name and are exposed only as `ctx.config` to that plugin's Lua hooks:

```toml
[plugins."demo-plugin"]
enabled = true
label = "ops"
regions = ["us-east-1", "eu-west-1"]
```

Table names must use `[plugins."<plugin-name>"]` for a loaded plugin. Keys are bare alphanumeric, `_`, or `-` names. Values may be strings, booleans, integers, or arrays of strings. Unknown settings inside a plugin table are preserved for that plugin; they are not core Shisa options.

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

AWS profile is resolved from `AWS_PROFILE`; when unset, Shisa reads `~/.aws/config` and uses `[default]` or the first `[profile <name>]` section. GCP project is cached from the active Cloud SDK config file under `~/.config/gcloud/configurations/`; Azure subscription is cached from `~/.azure/azureProfile.json`; Kubernetes context is cached from the first `KUBECONFIG` path, or `~/.kube/config`. The daemon registers native Linux inotify and macOS FSEvents invalidation scopes for these paths. Multiple providers render in one `cloud[...]` segment with ASCII provider markers: `aws`, `gcp`, `az`, and `k8s`.

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
- `[prompt].command_context` must be `"off"`, `"right"`, or `"message"`; configured command names are unique and contain only letters, digits, `_`, `-`, or `.`.
- `[prompt].command_context_modules` must be an array of unique core module ids or loaded plugin module ids.
- Each module in `[prompt].modules` and `[prompt].right_modules` must be a known core module id or a loaded plugin module id.
- `[plugins."<plugin-name>"]` names an installed-plugin namespace and accepts string, bool, integer, or string-array values.
- `[modules.<id>]` must reference a known module id.
- Unknown keys in known tables are invalid.
- Type mismatch, range violation, duplicate module id, and unknown module id errors must include file, line, and column.
