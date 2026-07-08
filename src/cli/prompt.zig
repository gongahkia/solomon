const std = @import("std");
const builtin = @import("builtin");
const cli_theme = @import("theme.zig");
const cli_util = @import("util.zig");
const client = @import("../shisa-client.zig");
const cloud_ctx_module = @import("../daemon/modules/cloud_ctx.zig");
const dispatcher = @import("../daemon/dispatcher.zig");
const git_branch_module = @import("../daemon/modules/git_branch.zig");
const language_versions_module = @import("../daemon/modules/language_versions.zig");
const paths = @import("../daemon/paths.zig");
const proto = @import("../proto/types.zig");
const prompt_payload = @import("prompt_payload.zig");
const shisa_config = @import("../config.zig");
const theme_loader = @import("theme_loader");

const max_config_bytes = 1024 * 1024;

const PromptConfig = prompt_payload.Config;
const buildPromptPayload = prompt_payload.buildPromptPayload;
const buildPromptPayloadWithModuleOptions = prompt_payload.buildPromptPayloadWithModuleOptions;
const defaultPromptModuleOptions = prompt_payload.defaultPromptModuleOptions;
const promptModuleOptions = prompt_payload.promptModuleOptions;
const promptRtl = prompt_payload.promptRtl;
const promptRtlReverse = prompt_payload.promptRtlReverse;

pub fn reportPromptPayloadBenchIterationAlloc(allocator: std.mem.Allocator) ![]u8 {
    const cwd = std.fs.cwd().realpathAlloc(allocator, ".");
    const resolved_cwd = cwd catch |err| return err;
    defer allocator.free(resolved_cwd);
    const config = PromptConfig{ .no_async = true, .cols = 80, .rows = 24 };
    const module_options = defaultPromptModuleOptions();
    return buildPromptPayloadWithModuleOptions(allocator, config, resolved_cwd, module_options);
}

const prompt_auto_spawn_grace_ms: i64 = 100;

pub fn promptCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var config = try parsePrompt(args);
    const debug_level = try shisaDebugLevel(allocator);
    if (debug_level > 0) config.trace = true;
    if (config.explain_a11y) {
        const output = try promptA11yExplanationAlloc(allocator);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);
    if (config.transient) {
        const transient = try transientPromptAlloc(allocator, cwd);
        defer allocator.free(transient);
        try std.fs.File.stdout().writeAll(transient);
        return;
    }
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    const payload = try buildPromptPayload(allocator, config, cwd);
    defer allocator.free(payload);

    if (config.instant) {
        if (try readInstantPrompt(allocator)) |cached| {
            defer allocator.free(cached);
            try writePromptTraceIfEnabled(allocator, config, cwd, debug_level);
            try writePromptText(allocator, cached, config.a11y, cwd);
            return;
        }
    }

    const response_payload = client.requestAlloc(allocator, socket_path, payload) catch |err| response: {
        if (!config.auto_spawn) return err;
        if (try autoSpawnPromptRequestAlloc(allocator, socket_path, payload)) |retried| break :response retried;
        if (config.right) return;
        const prompt_text = try renderSyncPromptAlloc(allocator, config, cwd);
        defer allocator.free(prompt_text);
        if (config.instant) {
            try writeInstantPrompt(allocator, prompt_text);
        }
        try writePromptTraceIfEnabled(allocator, config, cwd, debug_level);
        try writePromptText(allocator, prompt_text, config.a11y, cwd);
        return;
    };
    defer allocator.free(response_payload);

    var parsed = try std.json.parseFromSlice(proto.Response, allocator, response_payload, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (config.instant) {
        try writeInstantPrompt(allocator, parsed.value.prompt);
    }
    if (debug_level > 0) {
        if (parsed.value.trace) |trace| {
            try writeProtoTraceReport(allocator, cwd, trace, parsed.value.elapsed_us * 1000, debug_level);
        } else {
            try writePromptTraceIfEnabled(allocator, config, cwd, debug_level);
        }
    }
    if (config.right) {
        if (parsed.value.right_prompt) |right_prompt| try std.fs.File.stdout().writeAll(right_prompt);
        return;
    }
    try writePromptText(allocator, parsed.value.prompt, config.a11y, cwd);
}

pub fn traceCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(trace_help_text);
        return;
    }
    var config = try parsePrompt(args);
    config.trace = true;
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);
    var rendered = try renderLocalPrompt(allocator, config, cwd, true);
    defer rendered.deinit(allocator);
    try writeTraceReport(allocator, cwd, rendered.trace orelse &.{}, rendered.total_ns, 2);
    if (!config.right) try writePromptText(allocator, rendered.prompt, config.a11y, cwd);
}

fn shisaDebugLevel(allocator: std.mem.Allocator) !u8 {
    const raw = std.process.getEnvVarOwned(allocator, "SHISA_DEBUG") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return 0,
        else => return err,
    };
    defer allocator.free(raw);
    if (std.mem.eql(u8, raw, "2")) return 2;
    if (std.mem.eql(u8, raw, "1") or std.mem.eql(u8, raw, "true") or std.mem.eql(u8, raw, "yes")) return 1;
    return 0;
}

fn writePromptTraceIfEnabled(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8, debug_level: u8) !void {
    if (debug_level == 0) return;
    var rendered = renderLocalPrompt(allocator, config, cwd, true) catch |err| {
        const line = try std.fmt.allocPrint(allocator, "[shisa] trace_error={s}\n", .{@errorName(err)});
        defer allocator.free(line);
        try std.fs.File.stderr().writeAll(line);
        return;
    };
    defer rendered.deinit(allocator);
    try writeTraceReport(allocator, cwd, rendered.trace orelse &.{}, rendered.total_ns, debug_level);
}

fn parsePrompt(args: []const []const u8) !PromptConfig {
    var config = PromptConfig{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--exit")) {
            config.exit = try std.fmt.parseInt(i32, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--jobs")) {
            config.jobs = try std.fmt.parseInt(u32, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--duration-ms")) {
            config.duration_ms = try std.fmt.parseInt(u64, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--time")) {
            config.time = true;
        } else if (std.mem.eql(u8, arg, "--no-async")) {
            config.no_async = true;
        } else if (std.mem.eql(u8, arg, "--instant")) {
            config.instant = true;
        } else if (std.mem.eql(u8, arg, "--auto-spawn")) {
            config.auto_spawn = true;
        } else if (std.mem.eql(u8, arg, "--a11y")) {
            config.a11y = true;
        } else if (std.mem.eql(u8, arg, "--explain-a11y")) {
            config.explain_a11y = true;
        } else if (std.mem.eql(u8, arg, "--rtl")) {
            config.rtl = true;
        } else if (std.mem.eql(u8, arg, "--rtl-reverse")) {
            config.rtl_reverse = true;
        } else if (std.mem.eql(u8, arg, "--right")) {
            config.right = true;
        } else if (std.mem.eql(u8, arg, "--transient")) {
            config.transient = true;
        } else if (std.mem.eql(u8, arg, "--shell")) {
            config.shell = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cols")) {
            config.cols = try std.fmt.parseInt(u16, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--rows")) {
            config.rows = try std.fmt.parseInt(u16, try cli_util.nextValue(args, &i), 10);
        } else {
            return error.UnknownPromptArgument;
        }
    }

    return config;
}

fn transientPromptAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
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
    const format = parsed.transient_prompt orelse return allocator.dupe(u8, "");
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    return renderTransientFormatAlloc(allocator, format, cwd, home);
}

fn renderTransientFormatAlloc(allocator: std.mem.Allocator, format: []const u8, cwd: []const u8, home: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var index: usize = 0;
    while (index < format.len) : (index += 1) {
        if (format[index] != '%' or index + 1 >= format.len) {
            try out.append(allocator, format[index]);
            continue;
        }
        index += 1;
        switch (format[index]) {
            '%' => try out.append(allocator, '%'),
            '~' => {
                const display = try transientCwdAlloc(allocator, cwd, home);
                defer allocator.free(display);
                try out.appendSlice(allocator, display);
            },
            'd' => try out.appendSlice(allocator, cwd),
            else => {
                try out.append(allocator, '%');
                try out.append(allocator, format[index]);
            },
        }
    }
    return out.toOwnedSlice(allocator);
}

fn transientCwdAlloc(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8) ![]u8 {
    if (home) |home_path| {
        if (home_path.len > 0 and std.mem.startsWith(u8, cwd, home_path)) {
            if (cwd.len == home_path.len) return allocator.dupe(u8, "~");
            if (cwd.len > home_path.len and cwd[home_path.len] == '/') {
                return std.fmt.allocPrint(allocator, "~{s}", .{cwd[home_path.len..]});
            }
        }
    }
    return allocator.dupe(u8, cwd);
}

fn promptA11yExplanationAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);
    var config_diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &config_diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, config_diagnostic.line, config_diagnostic.column, config_diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);

    const theme_path = try cli_theme.pathAlloc(allocator, parsed.theme);
    defer allocator.free(theme_path);
    const theme_source = try std.fs.cwd().readFileAlloc(allocator, theme_path, max_config_bytes);
    defer allocator.free(theme_source);
    var theme_diagnostic: theme_loader.Diagnostic = .{};
    var theme = theme_loader.parse(allocator, theme_source, &theme_diagnostic) catch |err| switch (err) {
        error.InvalidTheme => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ theme_path, theme_diagnostic.line, theme_diagnostic.column, theme_diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer theme.deinit(allocator);

    return a11yExplanationAlloc(allocator, parsed, theme);
}

fn a11yExplanationAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config, theme: theme_loader.Theme) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator, "a11y:\n");
    for (parsed.prompt_modules) |module_id| {
        const id = shisa_config.moduleIdName(module_id);
        const label = if (cli_theme.findSegment(theme, id)) |segment|
            if (segment.a11y.len > 0) segment.a11y else coreA11yLabel(module_id)
        else
            coreA11yLabel(module_id);
        try cli_util.appendFmt(allocator, &out, "  {s}: {s}\n", .{ id, label });
    }
    return out.toOwnedSlice(allocator);
}

fn coreA11yLabel(module_id: shisa_config.ModuleId) []const u8 {
    return switch (module_id) {
        .cwd => "current directory",
        .git_branch => "git branch",
        .language_versions => "language versions",
        .exit_status => "exit status",
        .jobs => "background jobs",
        .cmd_duration => "command duration",
        .user_host => "user and host",
        .cloud_ctx => "cloud context",
        .cdhint => "cd hint",
        .tmux_pane => "tmux pane",
        .risk_tier => "risk tier",
        .sso_expiry => "SSO expiry",
        .iac_workspace => "infrastructure workspace",
        .region_drift => "region drift",
        .cost_glance => "cost glance",
        .vpn_status => "VPN status",
        .ssh_target => "SSH target",
        .container_provenance => "container provenance",
        .time => "time",
    };
}

fn spawnPromptDaemon(allocator: std.mem.Allocator, socket_path: []const u8) !void {
    const daemon_path = try cli_util.siblingExecutablePath(allocator, "shisad");
    defer allocator.free(daemon_path);
    var daemon = std.process.Child.init(&.{ daemon_path, "--foreground", "--socket", socket_path }, allocator);
    daemon.stdin_behavior = .Ignore;
    daemon.stdout_behavior = .Ignore;
    daemon.stderr_behavior = .Ignore;
    try daemon.spawn();
}

fn autoSpawnPromptRequestAlloc(allocator: std.mem.Allocator, socket_path: []const u8, payload: []const u8) !?[]u8 {
    spawnPromptDaemon(allocator, socket_path) catch return null;
    cli_util.waitForPath(socket_path, prompt_auto_spawn_grace_ms) catch return null;
    return client.requestAlloc(allocator, socket_path, payload) catch null;
}

const LocalPromptRender = struct {
    prompt: []u8,
    trace: ?[]dispatcher.TraceEntry = null,
    total_ns: u64 = 0,

    fn deinit(self: *LocalPromptRender, allocator: std.mem.Allocator) void {
        allocator.free(self.prompt);
        if (self.trace) |trace| allocator.free(trace);
        self.* = undefined;
    }
};

fn renderSyncPromptAlloc(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8) ![]u8 {
    const rendered = try renderLocalPrompt(allocator, config, cwd, false);
    if (rendered.trace) |trace| allocator.free(trace);
    return rendered.prompt;
}

fn renderLocalPrompt(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8, trace_enabled: bool) !LocalPromptRender {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(allocator);

    var module_options = try promptModuleOptions(allocator);
    defer module_options.deinit(allocator);
    const pipeline = try promptPipelineAlloc(allocator, module_options.modules);
    defer allocator.free(pipeline);
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch null;
    defer if (home) |value| allocator.free(value);
    const kubeconfig = std.process.getEnvVarOwned(allocator, "KUBECONFIG") catch null;
    defer if (kubeconfig) |value| allocator.free(value);
    const ssh = std.process.getEnvVarOwned(allocator, "SSH_CONNECTION") catch null;
    defer if (ssh) |value| allocator.free(value);
    const aws_profile = std.process.getEnvVarOwned(allocator, "AWS_PROFILE") catch null;
    defer if (aws_profile) |value| allocator.free(value);
    const aws_region = std.process.getEnvVarOwned(allocator, "AWS_REGION") catch null;
    defer if (aws_region) |value| allocator.free(value);
    const aws_default_region = std.process.getEnvVarOwned(allocator, "AWS_DEFAULT_REGION") catch null;
    defer if (aws_default_region) |value| allocator.free(value);
    const cloudsdk_compute_region = std.process.getEnvVarOwned(allocator, "CLOUDSDK_COMPUTE_REGION") catch null;
    defer if (cloudsdk_compute_region) |value| allocator.free(value);
    const azure_location = std.process.getEnvVarOwned(allocator, "AZURE_LOCATION") catch null;
    defer if (azure_location) |value| allocator.free(value);
    const arm_location = std.process.getEnvVarOwned(allocator, "ARM_LOCATION") catch null;
    defer if (arm_location) |value| allocator.free(value);
    const azure_default_location = std.process.getEnvVarOwned(allocator, "AZURE_DEFAULT_LOCATION") catch null;
    defer if (azure_default_location) |value| allocator.free(value);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const user = try currentUserAlloc(allocator);
    defer allocator.free(user);
    const host = try currentHostAlloc(allocator);
    defer allocator.free(host);

    const cache_set = dispatcher.CacheSet{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    };
    var style_state = loadPromptStyleAlloc(allocator, module_options.theme, config) catch null;
    defer if (style_state) |*state| state.deinit(allocator);
    const render_input = dispatcher.RenderInput{
        .cwd = cwd,
        .home = home,
        .exit = config.exit,
        .jobs = config.jobs,
        .duration_ms = config.duration_ms,
        .time = config.time,
        .no_async = if (trace_enabled) config.no_async else true,
        .timestamp = std.time.timestamp(),
        .ssh = ssh,
        .user = user,
        .host = host,
        .aws_profile = aws_profile,
        .aws_region = aws_region,
        .aws_default_region = aws_default_region,
        .cloudsdk_compute_region = cloudsdk_compute_region,
        .azure_location = azure_location,
        .arm_location = arm_location,
        .azure_default_location = azure_default_location,
        .kubeconfig = kubeconfig,
        .cloud_ctx = .{
            .aws = module_options.cloud_ctx.aws,
            .gcp = module_options.cloud_ctx.gcp,
            .azure = module_options.cloud_ctx.azure,
            .kubernetes = module_options.cloud_ctx.kubernetes,
        },
        .cdhint = module_options.cdhint,
        .tmux_pane = tmux_pane,
        .tmux_pane_options = module_options.tmux_pane,
        .rtl = promptRtl(config, module_options),
        .rtl_reverse = promptRtlReverse(config, module_options),
        .risk_tier = module_options.risk_tier,
        .sso_expiry = module_options.sso_expiry,
    };
    const rendered = if (trace_enabled)
        try dispatcher.renderPipelineTraced(allocator, cache_set, render_input, pipeline)
    else if (style_state) |*state|
        try dispatcher.renderPipelineStyled(allocator, cache_set, render_input, pipeline, state.style())
    else
        try dispatcher.renderPipeline(allocator, cache_set, render_input, pipeline);
    const prompt_text = rendered.prompt;
    const trace = rendered.trace;
    const total_ns = rendered.total_ns;
    if (rendered.redraw_token) |token| allocator.free(token);
    return .{
        .prompt = prompt_text,
        .trace = trace,
        .total_ns = total_ns,
    };
}

const PromptStyleState = struct {
    theme: theme_loader.Theme,
    color_caps: theme_loader.contrast.ColorCaps,
    glyph_tier: theme_loader.GlyphTier,

    fn deinit(self: *PromptStyleState, allocator: std.mem.Allocator) void {
        self.theme.deinit(allocator);
        self.* = undefined;
    }

    fn style(self: *const PromptStyleState) dispatcher.StyleConfig {
        return .{
            .theme = &self.theme,
            .color_caps = self.color_caps,
            .glyph_tier = self.glyph_tier,
        };
    }
};

fn loadPromptStyleAlloc(allocator: std.mem.Allocator, theme_arg: []const u8, config: PromptConfig) !PromptStyleState {
    const theme_path = try cli_theme.pathAlloc(allocator, theme_arg);
    defer allocator.free(theme_path);
    const theme_source = try std.fs.cwd().readFileAlloc(allocator, theme_path, max_config_bytes);
    defer allocator.free(theme_source);
    var theme_diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(allocator, theme_source, &theme_diagnostic);
    errdefer theme.deinit(allocator);
    return .{
        .theme = theme,
        .color_caps = effectivePromptColorCaps(theme, config),
        .glyph_tier = effectivePromptGlyphTier(theme, config),
    };
}

fn effectivePromptColorCaps(theme: theme_loader.Theme, config: PromptConfig) theme_loader.contrast.ColorCaps {
    if (config.a11y) return .none;
    return cli_theme.colorCapsForTheme(theme);
}

fn effectivePromptGlyphTier(theme: theme_loader.Theme, config: PromptConfig) theme_loader.GlyphTier {
    if (config.a11y) return .ascii;
    return switch (theme.capabilities.glyphs) {
        .ascii => .ascii,
        .nerd_font => .unicode,
    };
}

fn writeTraceReport(allocator: std.mem.Allocator, cwd: []const u8, trace: []const dispatcher.TraceEntry, total_ns: u64, debug_level: u8) !void {
    try traceLine(allocator, "[shisa] cwd={s}\n", .{cwd});
    for (trace) |entry| {
        const ms = durationMs(entry.duration_ns);
        try traceLine(allocator, "[shisa] module={s} {s} {d:.2}ms cache={s}", .{
            dispatcher.moduleIdName(entry.module_id),
            executionClassName(entry.execution_class),
            ms,
            entry.cache_state,
        });
        if (entry.placeholder) try std.fs.File.stderr().writeAll(" placeholder=true");
        if (debug_level >= 2) {
            try traceLine(allocator, " key=module:{s} age_ms=0 hit_rate=n/a", .{dispatcher.moduleIdName(entry.module_id)});
        }
        try std.fs.File.stderr().writeAll("\n");
    }
    try traceLine(allocator, "[shisa] total {d:.2}ms modules={d}\n", .{ durationMs(total_ns), trace.len });
}

fn writeProtoTraceReport(allocator: std.mem.Allocator, cwd: []const u8, trace: []const proto.TraceEntry, total_ns: u64, debug_level: u8) !void {
    try traceLine(allocator, "[shisa] cwd={s}\n", .{cwd});
    for (trace) |entry| {
        try traceLine(allocator, "[shisa] module={s} {s} {d:.2}ms cache={s}", .{
            entry.module,
            entry.class,
            durationMs(entry.duration_ns),
            entry.cache_state,
        });
        if (entry.placeholder) try std.fs.File.stderr().writeAll(" placeholder=true");
        if (debug_level >= 2) {
            try traceLine(allocator, " key=module:{s} age_ms=0 hit_rate=n/a", .{entry.module});
        }
        try std.fs.File.stderr().writeAll("\n");
    }
    try traceLine(allocator, "[shisa] total {d:.2}ms modules={d}\n", .{ durationMs(total_ns), trace.len });
}

fn traceLine(allocator: std.mem.Allocator, comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try std.fs.File.stderr().writeAll(line);
}

fn durationMs(duration_ns: u64) f64 {
    return @as(f64, @floatFromInt(duration_ns)) / @as(f64, @floatFromInt(std.time.ns_per_ms));
}

fn executionClassName(class: dispatcher.ExecutionClass) []const u8 {
    return switch (class) {
        .sync => "sync",
        .cached => "cached",
        .async => "async",
    };
}

fn currentUserAlloc(allocator: std.mem.Allocator) ![]u8 {
    const env_name = if (builtin.os.tag == .windows) "USERNAME" else "USER";
    return std.process.getEnvVarOwned(allocator, env_name) catch try allocator.dupe(u8, "unknown");
}

fn currentHostAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (builtin.os.tag == .windows) {
        return std.process.getEnvVarOwned(allocator, "COMPUTERNAME") catch try allocator.dupe(u8, "unknown");
    }
    var host_buffer: [std.posix.HOST_NAME_MAX]u8 = undefined;
    const host = std.posix.gethostname(&host_buffer) catch "unknown";
    return allocator.dupe(u8, host);
}

fn promptPipelineAlloc(allocator: std.mem.Allocator, modules: []const shisa_config.ModuleId) ![]dispatcher.ModuleSpec {
    const pipeline = try allocator.alloc(dispatcher.ModuleSpec, modules.len);
    errdefer allocator.free(pipeline);
    for (modules, 0..) |module_id, index| {
        const id = dispatcherModuleId(module_id);
        pipeline[index] = .{
            .id = id,
            .execution_class = dispatcher.executionClass(id),
        };
    }
    return pipeline;
}

fn dispatcherModuleId(module_id: shisa_config.ModuleId) dispatcher.ModuleId {
    return switch (module_id) {
        .cwd => .cwd,
        .git_branch => .git_branch,
        .language_versions => .language_versions,
        .time => .time,
        .exit_status => .exit_status,
        .jobs => .jobs,
        .cmd_duration => .cmd_duration,
        .user_host => .user_host,
        .cloud_ctx => .cloud_ctx,
        .cdhint => .cdhint,
        .tmux_pane => .tmux_pane,
        .risk_tier => .risk_tier,
        .sso_expiry => .sso_expiry,
        .iac_workspace => .iac_workspace,
        .region_drift => .region_drift,
        .cost_glance => .cost_glance,
        .vpn_status => .vpn_status,
        .ssh_target => .ssh_target,
        .container_provenance => .container_provenance,
    };
}

fn writePromptText(allocator: std.mem.Allocator, prompt_text: []const u8, a11y: bool, cwd: []const u8) !void {
    const osc7 = try osc7SequenceAlloc(allocator, cwd);
    defer allocator.free(osc7);
    try std.fs.File.stdout().writeAll(osc7);
    if (!a11y) {
        try std.fs.File.stdout().writeAll(prompt_text);
        return;
    }
    const accessible = try a11yPromptAlloc(allocator, prompt_text);
    defer allocator.free(accessible);
    try std.fs.File.stdout().writeAll(accessible);
}

fn osc7SequenceAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
    const host = std.process.getEnvVarOwned(allocator, "HOSTNAME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => try allocator.dupe(u8, "localhost"),
        else => return err,
    };
    defer allocator.free(host);
    return osc7SequenceForHostAlloc(allocator, host, cwd);
}

fn osc7SequenceForHostAlloc(allocator: std.mem.Allocator, host: []const u8, cwd: []const u8) ![]u8 {
    const encoded_host = try percentEncodeUriComponentAlloc(allocator, host, false);
    defer allocator.free(encoded_host);
    const encoded_path = try percentEncodeUriComponentAlloc(allocator, cwd, true);
    defer allocator.free(encoded_path);
    return std.fmt.allocPrint(allocator, "\x1b]7;file://{s}{s}\x07", .{ encoded_host, encoded_path });
}

fn percentEncodeUriComponentAlloc(allocator: std.mem.Allocator, value: []const u8, keep_slash: bool) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    for (value) |byte| {
        if (isUriUnreserved(byte) or (keep_slash and byte == '/')) {
            try out.append(allocator, byte);
        } else {
            try out.append(allocator, '%');
            try out.append(allocator, hexDigit(byte >> 4));
            try out.append(allocator, hexDigit(byte & 0x0f));
        }
    }
    return out.toOwnedSlice(allocator);
}

fn isUriUnreserved(byte: u8) bool {
    return (byte >= 'A' and byte <= 'Z') or
        (byte >= 'a' and byte <= 'z') or
        (byte >= '0' and byte <= '9') or
        byte == '-' or byte == '.' or byte == '_' or byte == '~';
}

fn hexDigit(value: u8) u8 {
    return "0123456789ABCDEF"[value & 0x0f];
}

fn instantPromptPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir});
}

fn readInstantPrompt(allocator: std.mem.Allocator) !?[]u8 {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    return std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
}

fn writeInstantPrompt(allocator: std.mem.Allocator, prompt_text: []const u8) !void {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(prompt_text);
}

test "instant prompt read write roundtrip" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-instant-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const path = try std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir_path});
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{});
    try file.writeAll("cached> ");
    file.close();

    const cached = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024);
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("cached> ", cached);
}

test "osc7 sequence percent-encodes cwd" {
    const sequence = try osc7SequenceForHostAlloc(std.testing.allocator, "local host", "/tmp/a b/%");
    defer std.testing.allocator.free(sequence);
    try std.testing.expectEqualStrings("\x1b]7;file://local%20host/tmp/a%20b/%25\x07", sequence);
}

fn a11yPromptAlloc(allocator: std.mem.Allocator, prompt_text: []const u8) ![]u8 {
    const no_ansi = try stripAnsiAlloc(allocator, prompt_text);
    defer allocator.free(no_ansi);
    return normalizePromptGlyphsAlloc(allocator, no_ansi);
}

fn stripAnsiAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var index: usize = 0;
    while (index < value.len) {
        if (value[index] == 0x1b and index + 1 < value.len and value[index + 1] == '[') {
            index += 2;
            while (index < value.len) : (index += 1) {
                if (value[index] >= 0x40 and value[index] <= 0x7e) {
                    index += 1;
                    break;
                }
            }
            continue;
        }
        try out.append(allocator, value[index]);
        index += 1;
    }

    return out.toOwnedSlice(allocator);
}

fn normalizePromptGlyphsAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var index: usize = 0;
    while (index < value.len) {
        if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x92", "->")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x91", "up")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x93", "down")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x9c\x93", "ok")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x9c\x97", "x")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x80\xa6", "...")) {
            index += 3;
        } else {
            try out.append(allocator, value[index]);
            index += 1;
        }
    }

    return out.toOwnedSlice(allocator);
}

fn replaceGlyph(out: *std.ArrayList(u8), allocator: std.mem.Allocator, tail: []const u8, glyph: []const u8, replacement: []const u8) !bool {
    if (!std.mem.startsWith(u8, tail, glyph)) return false;
    try out.appendSlice(allocator, replacement);
    return true;
}

test "prompt args parse a11y" {
    const config = try parsePrompt(&.{ "--a11y", "--no-async" });
    try std.testing.expect(config.a11y);
    try std.testing.expect(config.no_async);
}

test "prompt args parse explain a11y" {
    const config = try parsePrompt(&.{"--explain-a11y"});
    try std.testing.expect(config.explain_a11y);
}

test "prompt args parse rtl flags" {
    const config = try parsePrompt(&.{ "--rtl", "--rtl-reverse" });
    try std.testing.expect(config.rtl);
    try std.testing.expect(config.rtl_reverse);
}

test "prompt args parse right flag" {
    const config = try parsePrompt(&.{"--right"});
    try std.testing.expect(config.right);
}

test "prompt args parse transient flag" {
    const config = try parsePrompt(&.{"--transient"});
    try std.testing.expect(config.transient);
}

test "transient format renders cwd escapes" {
    const output = try renderTransientFormatAlloc(std.testing.allocator, "%~ %% %d> ", "/Users/me/src/shisa", "/Users/me");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("~/src/shisa % /Users/me/src/shisa> ", output);
}

test "prompt args parse auto spawn" {
    const config = try parsePrompt(&.{"--auto-spawn"});
    try std.testing.expect(config.auto_spawn);
}

test "auto spawn uses 100ms grace" {
    try std.testing.expectEqual(@as(i64, 100), prompt_auto_spawn_grace_ms);
}

test "sync prompt fallback renders cwd prompt" {
    const dir_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-sync-fallback-{x}", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const output = try renderSyncPromptAlloc(std.testing.allocator, .{}, dir_path);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, dir_path) != null);
    try std.testing.expect(std.mem.endsWith(u8, output, "> "));
}

test "a11y prompt strips ansi and normalizes glyphs" {
    const output = try a11yPromptAlloc(std.testing.allocator, "\x1b[31mexit:2\x1b[0m \xe2\x86\x92 prod \xe2\x9c\x93\n");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("exit:2 -> prod ok\n", output);
}

test "a11y explanation dumps configured module labels" {
    var config_diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &config_diagnostic);
    defer parsed.deinit(std.testing.allocator);
    const theme_source = try std.fs.cwd().readFileAlloc(std.testing.allocator, "themes/plain.toml", max_config_bytes);
    defer std.testing.allocator.free(theme_source);
    var theme_diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(std.testing.allocator, theme_source, &theme_diagnostic);
    defer theme.deinit(std.testing.allocator);

    const output = try a11yExplanationAlloc(std.testing.allocator, parsed, theme);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "  cwd: current directory\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "  risk_tier: risk tier\n") != null);
}

const trace_help_text =
    \\usage: shisa trace [--cwd DIR] [--exit N] [--jobs N]
    \\
    \\options:
    \\  --cwd DIR        render as if current directory is DIR
    \\  --exit N         render with last exit code N
    \\  --jobs N         render with running job count N
    \\  --duration-ms N  render with command duration N
    \\  --shell NAME     render for zsh, bash, fish, nu, or pwsh
    \\
    \\trace output is written to stderr; prompt output remains on stdout.
    \\
;
