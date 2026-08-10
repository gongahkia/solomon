const std = @import("std");
const config = @import("shisa_config");

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);
    const output_path = if (args.len > 1) args[1] else "docs/config-schema.md";

    const docs = try generateAlloc(allocator);
    defer allocator.free(docs);

    var file = try std.fs.cwd().createFile(output_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(docs);
}

pub fn generateAlloc(allocator: std.mem.Allocator) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    const default_modules = try defaultModuleListAlloc(allocator);
    defer allocator.free(default_modules);

    try out.appendSlice(allocator,
        \\# `shisa.toml` Schema
        \\
        \\Generated from `src/config.zig` with `zig build config-schema-docs`.
        \\
        \\Shisa reads user config from `$XDG_CONFIG_HOME/shisa/shisa.toml`, falling back to `~/.config/shisa/shisa.toml`.
        \\
        \\## Minimal File
        \\
    );
    try out.append(allocator, '\n');
    try appendFmt(allocator, &out,
        \\```toml
        \\version = 1
        \\theme = "plain"
        \\locale = "auto"
        \\
        \\[prompt]
        \\modules = [{s}]
        \\right_modules = []
        \\rtl_reverse = false
        \\command_context = "off"
        \\command_context_commands = ["aws", "az", "gcloud", "helm", "kubectl", "terraform", "tofu"]
        \\command_context_modules = ["cloud_ctx", "risk_tier", "sso_expiry"]
        \\```
        \\
        \\## Top-Level Keys
        \\
        \\| Key | Type | Required | Default | Notes |
        \\| --- | --- | --- | --- | --- |
        \\| `version` | integer | yes | none | Must be `1`. |
        \\| `theme` | string | no | `"plain"` | Built-in theme id or absolute/tilde path to a theme TOML file. See `docs/theme-spec.md`. |
        \\| `locale` | string | no | `"auto"` | `auto` uses shell locale detection; otherwise a BCP 47-ish locale such as `en-US` or `ar-EG`. |
        \\| `transient_prompt` | string | no | none | Compact prompt format for accepted lines. Supports `%~` for cwd with home tilde, `%d` for raw cwd, and `%%` for a literal percent. |
        \\
        \\Unknown top-level keys are invalid.
        \\
        \\## `[prompt]`
        \\
        \\| Key | Type | Required | Default | Notes |
        \\| --- | --- | --- | --- | --- |
        \\| `modules` | array of strings | no | see below | Ordered left-prompt module pipeline. Values must be unique. |
        \\| `right_modules` | array of strings | no | `[]` | Ordered right-prompt module pipeline for shells with native right prompt support. Values must be unique. |
        \\| `rtl_reverse` | bool | no | `false` | Reverse rendered segment order only when the session is detected as RTL. |
        \\| `command_context` | string | no | `"off"` | Opt-in zsh command-aware target: `"off"`, `"right"`, or `"message"`. |
        \\| `command_context_commands` | array of strings | no | see below | Executable names that trigger command-aware context. |
        \\| `command_context_modules` | array of strings | no | see below | Modules rendered for a matching command. |
        \\
        \\Default module order:
        \\
        \\```toml
        \\[prompt]
        \\modules = [{s}]
        \\right_modules = []
        \\rtl_reverse = false
        \\command_context = "off"
        \\command_context_commands = ["aws", "az", "gcloud", "helm", "kubectl", "terraform", "tofu"]
        \\command_context_modules = ["cloud_ctx", "risk_tier", "sso_expiry"]
        \\```
        \\
        \\Command-aware context is disabled by default. zsh debounces command-buffer updates, asks the daemon to render only the configured modules, and displays the result on the selected target. It never evaluates the command line; quoted, piped, redirected, or compound commands do not trigger context. `"right"` and `"message"` are currently implemented in zsh only.
        \\
        \\Allowed core module ids for schema v1:
        \\
        \\| Module | Execution | Summary |
        \\| --- | --- | --- |
    , .{ default_modules, default_modules });
    try out.append(allocator, '\n');

    for (module_docs) |doc| {
        try appendFmt(allocator, &out, "| `{s}` | {s} | {s} |\n", .{
            config.moduleIdName(doc.id),
            config.moduleExecutionClass(doc.id),
            doc.summary,
        });
    }

    try out.appendSlice(allocator,
        \\
        \\Unknown module ids are invalid.
        \\
        \\## Plugin Configuration
        \\
        \\Plugin settings are namespaced by loaded plugin name and are exposed only as `ctx.config` to that plugin's Lua hooks:
        \\
        \\```toml
        \\[plugins."demo-plugin"]
        \\enabled = true
        \\label = "ops"
        \\regions = ["us-east-1", "eu-west-1"]
        \\```
        \\
        \\Table names must use `[plugins."<plugin-name>"]` for a loaded plugin. Keys are bare alphanumeric, `_`, or `-` names. Values may be strings, booleans, integers, or arrays of strings. Unknown settings inside a plugin table are preserved for that plugin; they are not core Shisa options.
        \\
        \\## Per-Module Options
        \\
        \\Per-module config lives under `[modules.<id>]`. Option tables may exist only for known module ids.
        \\
    );
    try out.append(allocator, '\n');

    try writeOptionsSection(allocator, &out, "cwd", &.{
        .{ .key = "truncate_to", .type = "integer", .default_value = "`3`", .constraints = "`0..16`; `0` disables truncation." },
        .{ .key = "home_tilde", .type = "bool", .default_value = "`true`", .constraints = "Replace `$HOME` prefix with `~`." },
        .{ .key = "max_width", .type = "integer", .default_value = "`0`", .constraints = "`0..512`; `0` disables display-width truncation." },
    }, "");
    try writeOptionsSection(allocator, &out, "git_branch", &.{
        .{ .key = "show_dirty", .type = "bool", .default_value = "`true`", .constraints = "Append `*` when worktree is dirty." },
        .{ .key = "cache_ttl_ms", .type = "integer", .default_value = "`250`", .constraints = "`0..60000`; `0` means no TTL reuse." },
    }, "");
    try writeOptionsSection(allocator, &out, "language_versions", &.{
        .{ .key = "detect", .type = "array of strings", .default_value = "`[\"python\", \"node\", \"rust\", \"go\"]`", .constraints = "Schema v1 recognizes these four values." },
        .{ .key = "path_hash_invalidate", .type = "bool", .default_value = "`false`", .constraints = "Opt-in. Include a SHA-256 hash of `$PATH` plus the active PATH in render requests so the daemon can invalidate and probe the correct toolchain." },
    }, "");
    try writeOptionsSection(allocator, &out, "exit_status", &.{
        .{ .key = "show_zero", .type = "bool", .default_value = "`false`", .constraints = "Show `exit:0` when true." },
    }, "");
    try writeOptionsSection(allocator, &out, "jobs", &.{
        .{ .key = "show_zero", .type = "bool", .default_value = "`false`", .constraints = "Show `jobs:0` when true." },
    }, "");
    try writeOptionsSection(allocator, &out, "cmd_duration", &.{
        .{ .key = "threshold_ms", .type = "integer", .default_value = "`1000`", .constraints = "`0..86400000`." },
    }, "");
    try writeOptionsSection(allocator, &out, "user_host", &.{
        .{ .key = "mode", .type = "string", .default_value = "`\"ssh\"`", .constraints = "One of `\"ssh\"`, `\"always\"`, `\"never\"`." },
    }, "");
    try writeOptionsSection(allocator, &out, "cloud_ctx", &.{
        .{ .key = "aws", .type = "bool", .default_value = "`true`", .constraints = "Show AWS profile context." },
        .{ .key = "gcp", .type = "bool", .default_value = "`true`", .constraints = "Show GCP project context." },
        .{ .key = "azure", .type = "bool", .default_value = "`true`", .constraints = "Show Azure subscription context." },
        .{ .key = "kubernetes", .type = "bool", .default_value = "`true`", .constraints = "Show Kubernetes context and namespace." },
    },
        \\AWS profile is resolved from `AWS_PROFILE`; when unset, Shisa reads `~/.aws/config` and uses `[default]` or the first `[profile <name>]` section. GCP project is cached from the active Cloud SDK config file under `~/.config/gcloud/configurations/`; Azure subscription is cached from `~/.azure/azureProfile.json`; Kubernetes context is cached from the first `KUBECONFIG` path, or `~/.kube/config`. The daemon registers native Linux inotify and macOS FSEvents invalidation scopes for these paths. Multiple providers render in one `cloud[...]` segment with ASCII provider markers: `aws`, `gcp`, `az`, and `k8s`.
        \\
    );
    try writeOptionsSection(allocator, &out, "cdhint", &.{
        .{ .key = "enabled", .type = "bool", .default_value = "`true`", .constraints = "Disable cdhint rendering when false." },
    },
        \\Place `.shisa-no-cdhint` in the current directory or detected project tree to suppress local cd hints for that tree.
        \\
    );
    try writeOptionsSection(allocator, &out, "tmux_pane", &.{
        .{ .key = "enabled", .type = "bool", .default_value = "`true`", .constraints = "Disable tmux pane rendering when false." },
    }, "");
    try writeOptionsSection(allocator, &out, "risk_tier", &.{
        .{ .key = "unknown_bg", .type = "string", .default_value = "`\"muted\"`", .constraints = "One of `\"fg\"`, `\"muted\"`, `\"accent\"`, `\"success\"`, `\"warning\"`, `\"danger\"`." },
        .{ .key = "dev_bg", .type = "string", .default_value = "`\"success\"`", .constraints = "Same as `unknown_bg`." },
        .{ .key = "staging_bg", .type = "string", .default_value = "`\"warning\"`", .constraints = "Same as `unknown_bg`." },
        .{ .key = "prod_bg", .type = "string", .default_value = "`\"danger\"`", .constraints = "Same as `unknown_bg`." },
    },
        \\These map risk tiers to prompt background-bar palette slots. Rule matching defaults and user-rule file format are documented in `docs/risk-tiers.md`.
        \\
    );
    try writeOptionsSection(allocator, &out, "sso_expiry", &.{
        .{ .key = "warning_minutes", .type = "integer", .default_value = "`30`", .constraints = "`1..1440`." },
    },
        \\Reads cached token expiry metadata only. Sources are documented in `docs/sso-expiry.md`.
        \\
    );
    try writeOptionsSection(allocator, &out, "time", &.{
        .{ .key = "format", .type = "string", .default_value = "`\"24h\"`", .constraints = "Only `\"24h\"` in schema v1." },
        .{ .key = "utc", .type = "bool", .default_value = "`true`", .constraints = "Must be `true` until local timezone support lands." },
    }, "");

    try out.appendSlice(allocator,
        \\## Validation Rules
        \\
        \\- `version` must be present and equal to `1`.
        \\- `[prompt].modules` must be an array of unique strings.
        \\- `[prompt].right_modules` must be an array of unique strings.
        \\- `[prompt].command_context` must be `"off"`, `"right"`, or `"message"`; configured command names are unique and contain only letters, digits, `_`, `-`, or `.`.
        \\- `[prompt].command_context_modules` must be an array of unique core module ids or loaded plugin module ids.
        \\- Each module in `[prompt].modules` and `[prompt].right_modules` must be a known core module id or a loaded plugin module id.
        \\- `[plugins."<plugin-name>"]` names an installed-plugin namespace and accepts string, bool, integer, or string-array values.
        \\- `[modules.<id>]` must reference a known module id.
        \\- Unknown keys in known tables are invalid.
        \\- Type mismatch, range violation, duplicate module id, and unknown module id errors must include file, line, and column.
    );
    try out.append(allocator, '\n');

    return out.toOwnedSlice(allocator);
}

const ModuleDoc = struct {
    id: config.ModuleId,
    summary: []const u8,
};

const module_docs = [_]ModuleDoc{
    .{ .id = .cwd, .summary = "Current directory, home-tilde, truncation." },
    .{ .id = .git_branch, .summary = "Git branch name and dirty marker." },
    .{ .id = .language_versions, .summary = "Python, Node, Rust, and Go versions for detected projects." },
    .{ .id = .exit_status, .summary = "Non-zero exit code segment." },
    .{ .id = .jobs, .summary = "Background job count." },
    .{ .id = .cmd_duration, .summary = "Last command duration above threshold." },
    .{ .id = .user_host, .summary = "User and host, normally only over SSH." },
    .{ .id = .cloud_ctx, .summary = "Experimental cloud account context; AWS, GCP, Azure, and Kubernetes support." },
    .{ .id = .cdhint, .summary = "Experimental compact local project-kind hint from marker files." },
    .{ .id = .tmux_pane, .summary = "Experimental current tmux pane id from `TMUX_PANE`." },
    .{ .id = .risk_tier, .summary = "Experimental risk classification and prompt background-bar mapping." },
    .{ .id = .sso_expiry, .summary = "Experimental cached SSO/session-expiry warning." },
    .{ .id = .iac_workspace, .summary = "Experimental Terraform/OpenTofu/Pulumi/CDK workspace metadata." },
    .{ .id = .region_drift, .summary = "Experimental provider-region drift warning." },
    .{ .id = .cost_glance, .summary = "Experimental compact local cloud-spend cache display." },
    .{ .id = .vpn_status, .summary = "Experimental active local VPN status." },
    .{ .id = .ssh_target, .summary = "Experimental remote SSH target and risk tier." },
    .{ .id = .container_provenance, .summary = "Experimental container/runtime provenance." },
    .{ .id = .time, .summary = "Optional UTC `HH:MM` clock segment." },
};

const OptionDoc = struct {
    key: []const u8,
    type: []const u8,
    default_value: []const u8,
    constraints: []const u8,
};

fn writeOptionsSection(allocator: std.mem.Allocator, out: *std.ArrayList(u8), table: []const u8, options: []const OptionDoc, note: []const u8) !void {
    try appendFmt(allocator, out,
        \\### `[modules.{s}]`
        \\
        \\| Key | Type | Default | Constraints |
        \\| --- | --- | --- | --- |
    , .{table});
    try out.append(allocator, '\n');
    for (options) |option| {
        try appendFmt(allocator, out, "| `{s}` | {s} | {s} | {s} |\n", .{ option.key, option.type, option.default_value, option.constraints });
    }
    try out.appendSlice(allocator, "\n");
    if (note.len != 0) {
        try out.appendSlice(allocator, note);
        try out.appendSlice(allocator, "\n");
    }
}

fn defaultModuleListAlloc(allocator: std.mem.Allocator) ![]u8 {
    var diagnostic: config.Diagnostic = .{};
    var parsed = try config.parse(allocator, config.default_config_text, &diagnostic);
    defer parsed.deinit(allocator);
    return moduleListAlloc(allocator, parsed.prompt_modules);
}

fn moduleListAlloc(allocator: std.mem.Allocator, modules: []const config.ModuleId) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (modules, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try appendFmt(allocator, &out, "\"{s}\"", .{config.moduleIdName(module_id)});
    }
    return out.toOwnedSlice(allocator);
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
}

test "generated config docs match checked-in file" {
    const generated = try generateAlloc(std.testing.allocator);
    defer std.testing.allocator.free(generated);
    const checked_in = try std.fs.cwd().readFileAlloc(std.testing.allocator, "docs/config-schema.md", 512 * 1024);
    defer std.testing.allocator.free(checked_in);
    try std.testing.expectEqualStrings(checked_in, generated);
}

test "default module docs stay quiet" {
    const modules = try defaultModuleListAlloc(std.testing.allocator);
    defer std.testing.allocator.free(modules);
    try std.testing.expect(std.mem.indexOf(u8, modules, "\"cloud_ctx\"") == null);
}
