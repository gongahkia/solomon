const std = @import("std");
const builtin = @import("builtin");
const cli_util = @import("util.zig");
const daemon_json = @import("../daemon/json.zig");
const risk_tier_module = @import("../daemon/modules/risk_tier.zig");
const shisa_config = @import("../config.zig");

pub const Config = struct {
    socket_path: ?[]const u8 = null,
    cwd: ?[]const u8 = null,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    time: bool = false,
    no_async: bool = false,
    render_continue: bool = false,
    async_status: bool = false,
    instant: bool = false,
    auto_spawn: bool = false,
    a11y: bool = false,
    explain_a11y: bool = false,
    rtl: bool = false,
    rtl_reverse: bool = false,
    right: bool = false,
    transient: bool = false,
    command_context: bool = false,
    commandline: ?[]const u8 = null,
    trace: bool = false,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
};

pub const ModuleOptions = struct {
    theme: []const u8 = "plain",
    locale: []const u8 = "auto",
    rtl_reverse: bool = false,
    modules: []const shisa_config.ModuleId,
    right_modules: []const shisa_config.ModuleId,
    command_context: shisa_config.CommandContextOptions = .{ .commands = &.{}, .modules = &.{} },
    owns_modules: bool = false,
    owns_command_context: bool = false,
    owns_theme: bool = false,
    owns_locale: bool = false,
    cwd: shisa_config.CwdOptions,
    git_branch: shisa_config.GitBranchOptions,
    exit_status: shisa_config.ExitStatusOptions,
    jobs: shisa_config.JobsOptions,
    cmd_duration: shisa_config.CmdDurationOptions,
    user_host: shisa_config.UserHostOptions,
    cloud_ctx: shisa_config.CloudCtxOptions,
    cdhint: shisa_config.CdhintOptions,
    tmux_pane: shisa_config.TmuxPaneOptions,
    language_versions: shisa_config.LanguageVersionsOptions,
    risk_tier: shisa_config.RiskTierOptions,
    sso_expiry: shisa_config.SsoExpiryOptions,

    pub fn deinit(self: *ModuleOptions, allocator: std.mem.Allocator) void {
        if (self.owns_modules) {
            allocator.free(self.modules);
            allocator.free(self.right_modules);
        }
        if (self.owns_command_context) {
            for (self.command_context.commands) |command| allocator.free(command);
            allocator.free(self.command_context.commands);
            allocator.free(self.command_context.modules);
        }
        if (self.owns_theme) allocator.free(self.theme);
        if (self.owns_locale) allocator.free(self.locale);
        self.* = undefined;
    }
};

const default_prompt_modules = [_]shisa_config.ModuleId{
    .cwd,
    .git_branch,
    .exit_status,
    .jobs,
    .cmd_duration,
    .user_host,
};
const command_context_primary_modules = [_]shisa_config.ModuleId{.cwd};

pub fn buildPromptPayload(allocator: std.mem.Allocator, config: Config, cwd: []const u8) ![]u8 {
    return buildPromptPayloadV2(allocator, config, cwd, false);
}

pub fn buildPromptPayloadWithPathHashInvalidation(allocator: std.mem.Allocator, config: Config, cwd: []const u8, path_hash_invalidate: bool) ![]u8 {
    return buildPromptPayloadV2(allocator, config, cwd, path_hash_invalidate);
}

/// Render requests deliberately contain only shell-owned, per-invocation
/// state. The daemon owns configuration, theme parsing, and module selection;
/// keeping them out of this function prevents prompt-time config I/O.
fn buildPromptPayloadV2(allocator: std.mem.Allocator, config: Config, cwd: []const u8, path_hash_invalidate: bool) ![]u8 {
    const escaped_cwd = try daemon_json.escapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try daemon_json.escapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const escaped_commandline = try daemon_json.escapeAlloc(allocator, config.commandline orelse "");
    defer allocator.free(escaped_commandline);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const escaped_tmux_pane = try daemon_json.escapeAlloc(allocator, tmux_pane orelse "");
    defer allocator.free(escaped_tmux_pane);
    const request_id = try std.fmt.allocPrint(allocator, "cli-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(request_id);
    const env_json = if (path_hash_invalidate)
        try pathEnvJsonAlloc(allocator)
    else
        try allocator.dupe(u8, "");
    defer allocator.free(env_json);
    const op = if (config.render_continue) "render_continue" else "render";

    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":2,\"op\":\"{s}\",\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d},\"tty\":\"/dev/tty\",\"color_caps\":\"{s}\",\"glyph_caps\":\"{s}\",\"user_id\":{d},\"session\":\"cli\",\"request_id\":\"{s}\"{s},\"tmux_pane\":\"{s}\",\"trace\":{},\"rtl\":{},\"command_context\":{},\"commandline\":\"{s}\"}}",
        .{ op, escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows, promptColorCaps(config), promptGlyphCaps(config), promptUserId(), request_id, env_json, escaped_tmux_pane, config.trace, config.rtl, config.command_context, escaped_commandline },
    );
}

pub fn buildPromptPayloadWithModuleOptions(allocator: std.mem.Allocator, config: Config, cwd: []const u8, module_options: ModuleOptions) ![]u8 {
    const escaped_cwd = try daemon_json.escapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try daemon_json.escapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const selected_context_modules = commandContextModules(config, module_options);
    const selected_modules = if (config.command_context) command_context_primary_modules[0..] else module_options.modules;
    const selected_right_modules = if (config.command_context) selected_context_modules else module_options.right_modules;
    const modules_json = try promptModulesJsonAlloc(allocator, selected_modules);
    defer allocator.free(modules_json);
    const right_modules_json = try promptModulesJsonAlloc(allocator, selected_right_modules);
    defer allocator.free(right_modules_json);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const escaped_tmux_pane = try daemon_json.escapeAlloc(allocator, tmux_pane orelse "");
    defer allocator.free(escaped_tmux_pane);
    const escaped_theme = try daemon_json.escapeAlloc(allocator, module_options.theme);
    defer allocator.free(escaped_theme);
    const request_id = try std.fmt.allocPrint(allocator, "cli-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(request_id);
    const rtl = promptRtl(config, module_options);
    const rtl_reverse = promptRtlReverse(config, module_options);
    const env_json = if (module_options.language_versions.path_hash_invalidate)
        try pathEnvJsonAlloc(allocator)
    else
        try allocator.dupe(u8, "");
    defer allocator.free(env_json);

    const head = try std.fmt.allocPrint(
        allocator,
        "{{\"v\":2,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d},\"tty\":\"/dev/tty\",\"color_caps\":\"{s}\",\"glyph_caps\":\"{s}\",\"theme\":\"{s}\",\"user_id\":{d},\"session\":\"cli\",\"request_id\":\"{s}\"{s},",
        .{ escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows, promptColorCaps(config), promptGlyphCaps(config), escaped_theme, promptUserId(), request_id, env_json },
    );
    defer allocator.free(head);
    const tail = try std.fmt.allocPrint(
        allocator,
        "\"modules\":[{s}],\"right_modules\":[{s}],\"tmux_pane\":\"{s}\",\"trace\":{},\"rtl\":{},\"rtl_reverse\":{},\"cwd_options\":{{\"truncate_to\":{d},\"home_tilde\":{},\"max_width\":{d}}},\"cloud_ctx\":{{\"aws\":{},\"gcp\":{},\"azure\":{},\"kubernetes\":{}}},\"cdhint\":{{\"enabled\":{}}},\"tmux_pane_options\":{{\"enabled\":{}}},\"risk_tier\":{{\"unknown_bg\":\"{s}\",\"dev_bg\":\"{s}\",\"staging_bg\":\"{s}\",\"prod_bg\":\"{s}\"}},\"sso_expiry\":{{\"warning_minutes\":{d}}}}}",
        .{ modules_json, right_modules_json, escaped_tmux_pane, config.trace, rtl, rtl_reverse, module_options.cwd.truncate_to, module_options.cwd.home_tilde, module_options.cwd.max_width, module_options.cloud_ctx.aws, module_options.cloud_ctx.gcp, module_options.cloud_ctx.azure, module_options.cloud_ctx.kubernetes, module_options.cdhint.enabled, module_options.tmux_pane.enabled, risk_tier_module.colorSlotName(module_options.risk_tier.unknown_bg), risk_tier_module.colorSlotName(module_options.risk_tier.dev_bg), risk_tier_module.colorSlotName(module_options.risk_tier.staging_bg), risk_tier_module.colorSlotName(module_options.risk_tier.prod_bg), module_options.sso_expiry.warning_minutes },
    );
    defer allocator.free(tail);
    return std.fmt.allocPrint(
        allocator,
        "{s}{s}",
        .{ head, tail },
    );
}

fn promptUserId() u32 {
    return switch (builtin.os.tag) {
        .windows => 0,
        else => std.posix.getuid(),
    };
}

fn pathEnvJsonAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = std.process.getEnvVarOwned(allocator, "PATH") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer allocator.free(path);
    const hash = try sha256HexAlloc(allocator, path);
    defer allocator.free(hash);
    const escaped_path = try daemon_json.escapeAlloc(allocator, path);
    defer allocator.free(escaped_path);
    return std.fmt.allocPrint(allocator, ",\"env_hash\":\"{s}\",\"path_env\":\"{s}\"", .{ hash, escaped_path });
}

fn sha256HexAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(value, &digest, .{});
    const hex = std.fmt.bytesToHex(digest, .lower);
    return allocator.dupe(u8, hex[0..]);
}

pub fn promptRtl(config: Config, module_options: ModuleOptions) bool {
    if (!std.mem.eql(u8, module_options.locale, "auto")) return shisa_config.localeIsRtl(module_options.locale);
    return config.rtl;
}

pub fn promptRtlReverse(config: Config, module_options: ModuleOptions) bool {
    return config.rtl_reverse or module_options.rtl_reverse;
}

fn promptModulesJsonAlloc(allocator: std.mem.Allocator, modules: []const shisa_config.ModuleId) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (modules, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ",");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    return out.toOwnedSlice(allocator);
}

fn promptColorCaps(config: Config) []const u8 {
    return if (config.a11y) "none" else "truecolor";
}

fn promptGlyphCaps(config: Config) []const u8 {
    return if (config.a11y) "ascii" else "unicode";
}

pub fn defaultPromptModuleOptions() ModuleOptions {
    return .{
        .theme = "plain",
        .locale = "auto",
        .rtl_reverse = false,
        .modules = default_prompt_modules[0..],
        .right_modules = &.{},
        .command_context = .{ .commands = &.{}, .modules = &.{} },
        .cwd = .{},
        .git_branch = .{},
        .exit_status = .{},
        .jobs = .{},
        .cmd_duration = .{},
        .user_host = .{},
        .cloud_ctx = .{},
        .cdhint = .{},
        .tmux_pane = .{},
        .language_versions = .{},
        .risk_tier = .{},
        .sso_expiry = .{},
    };
}

pub fn promptModuleOptions(allocator: std.mem.Allocator) !ModuleOptions {
    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);
    const modules = try allocator.dupe(shisa_config.ModuleId, parsed.prompt_modules);
    errdefer allocator.free(modules);
    const right_modules = try allocator.dupe(shisa_config.ModuleId, parsed.right_prompt_modules);
    errdefer allocator.free(right_modules);
    const theme = try allocator.dupe(u8, parsed.theme);
    errdefer allocator.free(theme);
    const locale = try allocator.dupe(u8, parsed.locale);
    errdefer allocator.free(locale);
    const command_context_commands = try dupStringSlice(allocator, parsed.command_context.commands);
    errdefer freeStringSlice(allocator, command_context_commands);
    const command_context_modules = try allocator.dupe(shisa_config.ModuleId, parsed.command_context.modules);
    errdefer allocator.free(command_context_modules);
    return .{
        .theme = theme,
        .locale = locale,
        .rtl_reverse = parsed.prompt.rtl_reverse,
        .modules = modules,
        .right_modules = right_modules,
        .command_context = .{
            .target = parsed.command_context.target,
            .commands = command_context_commands,
            .modules = command_context_modules,
        },
        .owns_modules = true,
        .owns_command_context = true,
        .owns_theme = true,
        .owns_locale = true,
        .cwd = parsed.modules.cwd,
        .git_branch = parsed.modules.git_branch,
        .exit_status = parsed.modules.exit_status,
        .jobs = parsed.modules.jobs,
        .cmd_duration = parsed.modules.cmd_duration,
        .user_host = parsed.modules.user_host,
        .cloud_ctx = parsed.modules.cloud_ctx,
        .cdhint = parsed.modules.cdhint,
        .tmux_pane = parsed.modules.tmux_pane,
        .language_versions = parsed.modules.language_versions,
        .risk_tier = parsed.modules.risk_tier,
        .sso_expiry = parsed.modules.sso_expiry,
    };
}

fn commandContextModules(config: Config, module_options: ModuleOptions) []const shisa_config.ModuleId {
    if (!config.command_context) return &.{};
    if (module_options.command_context.target == .off) return &.{};
    if (module_options.command_context.modules.len == 0) return &.{};
    const commandline = config.commandline orelse return &.{};
    const executable = commandContextExecutable(commandline) orelse return &.{};
    for (module_options.command_context.commands) |command| {
        if (std.mem.eql(u8, command, executable)) return module_options.command_context.modules;
    }
    return &.{};
}

pub fn commandContextExecutable(commandline: []const u8) ?[]const u8 {
    if (std.mem.indexOfAny(u8, commandline, "'\\\"`|;&()<>\n\r") != null) return null;
    var tokens = std.mem.tokenizeAny(u8, commandline, " \t");
    var skip_sudo_value = false;
    while (tokens.next()) |token| {
        if (token.len == 0) continue;
        if (skip_sudo_value) {
            skip_sudo_value = false;
            continue;
        }
        if (isEnvironmentAssignment(token)) continue;
        if (std.mem.eql(u8, token, "command") or std.mem.eql(u8, token, "builtin") or std.mem.eql(u8, token, "exec")) continue;
        if (std.mem.eql(u8, token, "sudo")) {
            continue;
        }
        if (std.mem.eql(u8, token, "env")) {
            continue;
        }
        if (token[0] == '-') {
            if (std.mem.eql(u8, token, "-u") or std.mem.eql(u8, token, "--user") or std.mem.eql(u8, token, "-g") or std.mem.eql(u8, token, "--group")) skip_sudo_value = true;
            continue;
        }
        const executable = std.fs.path.basename(token);
        if (executable.len == 0 or !isSafeCommandToken(executable)) return null;
        return executable;
    }
    return null;
}

fn isEnvironmentAssignment(token: []const u8) bool {
    const equals = std.mem.indexOfScalar(u8, token, '=') orelse return false;
    if (equals == 0) return false;
    for (token[0..equals], 0..) |byte, index| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_' or (index > 0 and byte == '-'))) return false;
    }
    return true;
}

fn isSafeCommandToken(token: []const u8) bool {
    for (token) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_' or byte == '-' or byte == '.')) return false;
    }
    return true;
}

fn dupStringSlice(allocator: std.mem.Allocator, values: []const []const u8) ![]const []const u8 {
    const out = try allocator.alloc([]const u8, values.len);
    var copied: usize = 0;
    errdefer {
        for (out[0..copied]) |value| allocator.free(value);
        allocator.free(out);
    }
    for (values, 0..) |value, index| {
        out[index] = try allocator.dupe(u8, value);
        copied += 1;
    }
    return out;
}

fn freeStringSlice(allocator: std.mem.Allocator, values: []const []const u8) void {
    for (values) |value| allocator.free(value);
    allocator.free(values);
}

test "prompt payload carries rtl flags" {
    const payload = try buildPromptPayload(std.testing.allocator, .{ .rtl = true, .rtl_reverse = true }, "/tmp");
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"rtl\":true") != null);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"rtl_reverse\"") == null);
}

test "prompt payload can continue an async render" {
    const payload = try buildPromptPayload(std.testing.allocator, .{ .render_continue = true }, "/tmp");
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"op\":\"render_continue\"") != null);
}

test "path hash inclusion follows the configured language invalidation setting" {
    const disabled = try buildPromptPayloadWithPathHashInvalidation(std.testing.allocator, .{}, "/tmp", false);
    defer std.testing.allocator.free(disabled);
    try std.testing.expect(std.mem.indexOf(u8, disabled, "\"env_hash\"") == null);
    try std.testing.expect(std.mem.indexOf(u8, disabled, "\"path_env\"") == null);

    const path = std.process.getEnvVarOwned(std.testing.allocator, "PATH") catch return error.SkipZigTest;
    std.testing.allocator.free(path);
    const enabled = try buildPromptPayloadWithPathHashInvalidation(std.testing.allocator, .{}, "/tmp", true);
    defer std.testing.allocator.free(enabled);
    try std.testing.expect(std.mem.indexOf(u8, enabled, "\"env_hash\":\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, enabled, "\"path_env\":\"") != null);
}

test "prompt payload locale override controls rtl" {
    var rtl_options = defaultPromptModuleOptions();
    rtl_options.locale = "ar-EG";
    const rtl_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", rtl_options);
    defer std.testing.allocator.free(rtl_payload);
    try std.testing.expect(std.mem.indexOf(u8, rtl_payload, "\"rtl\":true") != null);

    var ltr_options = defaultPromptModuleOptions();
    ltr_options.locale = "en-US";
    const ltr_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{ .rtl = true }, "/tmp", ltr_options);
    defer std.testing.allocator.free(ltr_payload);
    try std.testing.expect(std.mem.indexOf(u8, ltr_payload, "\"rtl\":false") != null);
}

test "prompt payload carries right modules" {
    var options = defaultPromptModuleOptions();
    options.right_modules = &.{.time};
    const payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", options);
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"right_modules\":[\"time\"]") != null);
}

test "command context selects configured modules only for matching commands" {
    const commands = [_][]const u8{ "kubectl", "terraform" };
    const context_modules = [_]shisa_config.ModuleId{ .cloud_ctx, .risk_tier };
    var options = defaultPromptModuleOptions();
    options.command_context = .{
        .target = .right,
        .commands = commands[0..],
        .modules = context_modules[0..],
    };
    const matching = try buildPromptPayloadWithModuleOptions(
        std.testing.allocator,
        .{ .command_context = true, .commandline = "sudo -u root kubectl get pods" },
        "/tmp",
        options,
    );
    defer std.testing.allocator.free(matching);
    try std.testing.expect(std.mem.indexOf(u8, matching, "\"modules\":[\"cwd\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, matching, "\"right_modules\":[\"cloud_ctx\",\"risk_tier\"]") != null);

    const nonmatching = try buildPromptPayloadWithModuleOptions(
        std.testing.allocator,
        .{ .command_context = true, .commandline = "git status" },
        "/tmp",
        options,
    );
    defer std.testing.allocator.free(nonmatching);
    try std.testing.expect(std.mem.indexOf(u8, nonmatching, "\"right_modules\":[]") != null);
}

test "command context executable rejects shell syntax" {
    try std.testing.expectEqualStrings("kubectl", commandContextExecutable("AWS_PROFILE=prod kubectl get pods").?);
    try std.testing.expectEqualStrings("terraform", commandContextExecutable("env TF_LOG=warn terraform plan").?);
    try std.testing.expect(commandContextExecutable("kubectl get pods; rm -rf /") == null);
    try std.testing.expect(commandContextExecutable("'kubectl' get pods") == null);
}

test "prompt payload carries env hash and path only when enabled" {
    const digest = try sha256HexAlloc(std.testing.allocator, "");
    defer std.testing.allocator.free(digest);
    try std.testing.expectEqualStrings("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", digest);

    const disabled = defaultPromptModuleOptions();
    const disabled_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", disabled);
    defer std.testing.allocator.free(disabled_payload);
    try std.testing.expect(std.mem.indexOf(u8, disabled_payload, "\"env_hash\"") == null);
    try std.testing.expect(std.mem.indexOf(u8, disabled_payload, "\"path_env\"") == null);

    const path = std.process.getEnvVarOwned(std.testing.allocator, "PATH") catch return error.SkipZigTest;
    std.testing.allocator.free(path);
    var enabled = defaultPromptModuleOptions();
    enabled.language_versions.path_hash_invalidate = true;
    const enabled_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", enabled);
    defer std.testing.allocator.free(enabled_payload);
    const marker = "\"env_hash\":\"";
    const start = std.mem.indexOf(u8, enabled_payload, marker) orelse return error.MissingEnvHash;
    const hash_start = start + marker.len;
    try std.testing.expect(enabled_payload.len >= hash_start + 65);
    for (enabled_payload[hash_start .. hash_start + 64]) |byte| {
        try std.testing.expect(std.ascii.isDigit(byte) or (byte >= 'a' and byte <= 'f'));
    }
    try std.testing.expectEqual(@as(u8, '"'), enabled_payload[hash_start + 64]);
    try std.testing.expect(std.mem.indexOf(u8, enabled_payload, "\"path_env\":\"") != null);
}

test "prompt caps switch for a11y" {
    try std.testing.expectEqualStrings("none", promptColorCaps(.{ .a11y = true }));
    try std.testing.expectEqualStrings("ascii", promptGlyphCaps(.{ .a11y = true }));
    try std.testing.expectEqualStrings("truecolor", promptColorCaps(.{}));
    try std.testing.expectEqualStrings("unicode", promptGlyphCaps(.{}));
}
