const std = @import("std");
const cdhint_module = @import("modules/cdhint.zig");
const cloud_ctx_module = @import("modules/cloud_ctx.zig");
const container_provenance_module = @import("modules/container_provenance.zig");
const cmd_duration_module = @import("modules/cmd_duration.zig");
const cost_glance_module = @import("modules/cost_glance.zig");
const cwd_module = @import("modules/cwd.zig");
const exit_status_module = @import("modules/exit_status.zig");
const git_branch_module = @import("modules/git_branch.zig");
const iac_workspace_module = @import("modules/iac_workspace.zig");
const jobs_module = @import("modules/jobs.zig");
const language_versions_module = @import("modules/language_versions.zig");
const region_drift_module = @import("modules/region_drift.zig");
const risk_tier_module = @import("modules/risk_tier.zig");
const ssh_target_module = @import("modules/ssh_target.zig");
const sso_expiry_module = @import("modules/sso_expiry.zig");
const time_module = @import("modules/time.zig");
const tmux_pane_module = @import("modules/tmux_pane.zig");
const unicode_width = @import("modules/unicode_width.zig");
const user_host_module = @import("modules/user_host.zig");
const vpn_status_module = @import("modules/vpn_status.zig");

pub const ExecutionClass = enum {
    sync,
    cached,
    async,
};

pub const ModuleId = enum {
    cwd,
    git_branch,
    language_versions,
    time,
    exit_status,
    jobs,
    cmd_duration,
    user_host,
    cloud_ctx,
    cdhint,
    tmux_pane,
    risk_tier,
    region_drift,
    cost_glance,
    vpn_status,
    ssh_target,
    container_provenance,
    sso_expiry,
    iac_workspace,
};

pub const ModuleSpec = struct {
    id: ModuleId,
    execution_class: ExecutionClass,
};

pub const RenderedPrompt = struct {
    prompt: []u8,
    redraw_token: ?[]u8 = null,
    slow_warning: ?SlowWarning = null,
    trace: ?[]TraceEntry = null,
    total_ns: u64 = 0,

    pub fn deinit(self: *RenderedPrompt, allocator: std.mem.Allocator) void {
        allocator.free(self.prompt);
        if (self.redraw_token) |token| allocator.free(token);
        if (self.trace) |trace| allocator.free(trace);
        self.* = undefined;
    }
};

pub const SlowWarning = struct {
    module_id: ModuleId,
    elapsed_ns: u64,
};

pub const TraceEntry = struct {
    module_id: ModuleId,
    execution_class: ExecutionClass,
    duration_ns: u64,
    cache_state: []const u8,
    placeholder: bool = false,
};

pub const LayoutLineInput = struct {
    left: []const u8,
    right: []const u8 = "",
};

const slow_warning_ns = 5 * std.time.ns_per_ms;

pub const RenderInput = struct {
    cwd: []const u8,
    home: ?[]const u8,
    exit: i32,
    jobs: u32,
    duration_ms: u64,
    time: bool,
    no_async: bool = false,
    timestamp: i64,
    ssh: ?[]const u8,
    user: []const u8,
    host: []const u8,
    env_hash: ?[]const u8 = null,
    path_env: ?[]const u8 = null,
    cwd_options: cwd_module.Options = .{},
    aws_profile: ?[]const u8 = null,
    aws_region: ?[]const u8 = null,
    aws_default_region: ?[]const u8 = null,
    cloudsdk_compute_region: ?[]const u8 = null,
    azure_location: ?[]const u8 = null,
    arm_location: ?[]const u8 = null,
    azure_default_location: ?[]const u8 = null,
    kubeconfig: ?[]const u8 = null,
    cloud_ctx: cloud_ctx_module.Options = .{},
    cdhint: cdhint_module.Options = .{},
    tmux_pane: ?[]const u8 = null,
    tmux_pane_options: tmux_pane_module.Options = .{},
    risk_tier: risk_tier_module.BarColors = .{},
    sso_expiry: sso_expiry_module.Options = .{},
    rtl: bool = false,
    rtl_reverse: bool = false,
};

pub const CacheSet = struct {
    git_branch: *git_branch_module.Cache,
    language_versions: *language_versions_module.Cache,
    cloud_ctx: *cloud_ctx_module.Cache,
};

const AsyncRender = struct {
    segment: ?[]u8 = null,
    pending: bool = false,

    fn deinit(self: *AsyncRender, allocator: std.mem.Allocator) void {
        if (self.segment) |segment| allocator.free(segment);
        self.* = .{};
    }
};

const default_pipeline = [_]ModuleSpec{
    .{ .id = .cwd, .execution_class = executionClass(.cwd) },
    .{ .id = .git_branch, .execution_class = executionClass(.git_branch) },
    .{ .id = .language_versions, .execution_class = executionClass(.language_versions) },
    .{ .id = .time, .execution_class = executionClass(.time) },
    .{ .id = .exit_status, .execution_class = executionClass(.exit_status) },
    .{ .id = .jobs, .execution_class = executionClass(.jobs) },
    .{ .id = .cmd_duration, .execution_class = executionClass(.cmd_duration) },
    .{ .id = .user_host, .execution_class = executionClass(.user_host) },
    .{ .id = .risk_tier, .execution_class = executionClass(.risk_tier) },
    .{ .id = .sso_expiry, .execution_class = executionClass(.sso_expiry) },
    .{ .id = .iac_workspace, .execution_class = executionClass(.iac_workspace) },
    .{ .id = .region_drift, .execution_class = executionClass(.region_drift) },
    .{ .id = .cost_glance, .execution_class = executionClass(.cost_glance) },
    .{ .id = .vpn_status, .execution_class = executionClass(.vpn_status) },
    .{ .id = .ssh_target, .execution_class = executionClass(.ssh_target) },
    .{ .id = .container_provenance, .execution_class = executionClass(.container_provenance) },
};

pub fn executionClass(module_id: ModuleId) ExecutionClass {
    return switch (module_id) {
        .git_branch, .language_versions => .async,
        else => .sync,
    };
}

pub fn renderDefault(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput) !RenderedPrompt {
    return renderPipeline(allocator, caches, input, default_pipeline[0..]);
}

pub fn renderDefaultTraced(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput) !RenderedPrompt {
    return renderPipelineTraced(allocator, caches, input, default_pipeline[0..]);
}

pub fn renderPipeline(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec) !RenderedPrompt {
    return renderPipelineWithTerminator(allocator, caches, input, pipeline, "> ");
}

pub fn renderPipelineTraced(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec) !RenderedPrompt {
    return renderPipelineWithOptions(allocator, caches, input, pipeline, "> ", true);
}

pub fn renderSegments(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec) !RenderedPrompt {
    return renderPipelineWithTerminator(allocator, caches, input, pipeline, "");
}

fn renderPipelineWithTerminator(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec, terminator: []const u8) !RenderedPrompt {
    return renderPipelineWithOptions(allocator, caches, input, pipeline, terminator, false);
}

fn renderPipelineWithOptions(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec, terminator: []const u8, trace_enabled: bool) !RenderedPrompt {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var wrote_segment = false;
    var has_async = false;
    var slow_warning: ?SlowWarning = null;
    var trace_entries: std.ArrayList(TraceEntry) = .empty;
    defer if (!trace_enabled) trace_entries.deinit(allocator);
    errdefer if (trace_enabled) trace_entries.deinit(allocator);
    const total_start_ns = std.time.nanoTimestamp();

    if (input.rtl and input.rtl_reverse) {
        var index = pipeline.len;
        while (index > 0) {
            index -= 1;
            try appendPipelineSegment(allocator, caches, input, pipeline[index], &out, &wrote_segment, &has_async, &slow_warning, if (trace_enabled) &trace_entries else null);
        }
    } else {
        for (pipeline) |spec| {
            try appendPipelineSegment(allocator, caches, input, spec, &out, &wrote_segment, &has_async, &slow_warning, if (trace_enabled) &trace_entries else null);
        }
    }

    try out.appendSlice(allocator, terminator);
    const trace = if (trace_enabled) try trace_entries.toOwnedSlice(allocator) else null;
    return .{
        .prompt = try out.toOwnedSlice(allocator),
        .redraw_token = if (has_async) try allocator.dupe(u8, "pending") else null,
        .slow_warning = slow_warning,
        .trace = trace,
        .total_ns = @intCast(std.time.nanoTimestamp() - total_start_ns),
    };
}

fn appendPipelineSegment(
    allocator: std.mem.Allocator,
    caches: CacheSet,
    input: RenderInput,
    spec: ModuleSpec,
    out: *std.ArrayList(u8),
    wrote_segment: *bool,
    has_async: *bool,
    slow_warning: *?SlowWarning,
    trace_entries: ?*std.ArrayList(TraceEntry),
) !void {
    var async_result: ?AsyncRender = null;
    defer if (async_result) |*value| value.deinit(allocator);

    const start_ns = std.time.nanoTimestamp();
    const segment = if (spec.execution_class == .async and !input.no_async) async: {
        async_result = try dispatchAsync(allocator, caches, spec.id, input);
        if (async_result.?.pending) has_async.* = true;
        if (async_result.?.segment) |value| break :async try allocator.dupe(u8, value);
        if (async_result.?.pending) break :async try placeholderAlloc(allocator, spec.id);
        break :async null;
    } else try dispatch(allocator, caches, spec.id, input);
    const elapsed_ns = @as(u64, @intCast(std.time.nanoTimestamp() - start_ns));
    if (slow_warning.* == null and elapsed_ns > slow_warning_ns) {
        slow_warning.* = .{ .module_id = spec.id, .elapsed_ns = elapsed_ns };
    }
    if (trace_entries) |entries| {
        try entries.append(allocator, .{
            .module_id = spec.id,
            .execution_class = spec.execution_class,
            .duration_ns = elapsed_ns,
            .cache_state = traceCacheState(spec, input, async_result),
            .placeholder = async_result != null and async_result.?.pending and async_result.?.segment == null,
        });
    }
    defer if (segment) |value| allocator.free(value);
    if (segment) |value| {
        if (wrote_segment.*) try out.append(allocator, ' ');
        try out.appendSlice(allocator, value);
        wrote_segment.* = true;
    }
}

fn traceCacheState(spec: ModuleSpec, input: RenderInput, async_result: ?AsyncRender) []const u8 {
    if (spec.execution_class != .async) return "none";
    if (input.no_async) return "bypass";
    if (async_result) |result| {
        if (result.segment != null) return "hit";
        if (result.pending) return "miss";
    }
    return "miss";
}

pub fn fillerWidth(left: []const u8, right: []const u8, cols: u16) usize {
    const used = visibleWidth(left) + visibleWidth(right);
    const total: usize = cols;
    return if (used < total) total - used else 0;
}

pub fn renderAlignedLineAlloc(allocator: std.mem.Allocator, left: []const u8, right: []const u8, cols: u16) ![]u8 {
    if (right.len == 0) return allocator.dupe(u8, left);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator, left);
    try out.appendNTimes(allocator, ' ', fillerWidth(left, right, cols));
    try out.appendSlice(allocator, right);
    return out.toOwnedSlice(allocator);
}

pub fn renderLayoutLinesAlloc(allocator: std.mem.Allocator, lines: []const LayoutLineInput, cols: u16) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (lines) |line| {
        const rendered = try renderAlignedLineAlloc(allocator, line.left, line.right, cols);
        defer allocator.free(rendered);
        try out.appendSlice(allocator, rendered);
        try out.append(allocator, '\n');
    }
    return out.toOwnedSlice(allocator);
}

pub fn visibleWidth(value: []const u8) usize {
    var width: usize = 0;
    var index: usize = 0;
    while (index < value.len) {
        if (value[index] == 0x1b and index + 1 < value.len) {
            if (value[index + 1] == '[') {
                index = skipCsi(value, index + 2);
                continue;
            }
            if (value[index + 1] == ']') {
                index = skipOsc(value, index + 2);
                continue;
            }
        }
        const len = std.unicode.utf8ByteSequenceLength(value[index]) catch 1;
        if (index + len > value.len) {
            width += 1;
            index += 1;
            continue;
        }
        const codepoint = std.unicode.utf8Decode(value[index .. index + len]) catch {
            width += 1;
            index += 1;
            continue;
        };
        width += unicode_width.codepointWidth(codepoint);
        index += @min(len, value.len - index);
    }
    return width;
}

fn skipCsi(value: []const u8, start: usize) usize {
    var index = start;
    while (index < value.len) : (index += 1) {
        if (value[index] >= 0x40 and value[index] <= 0x7e) return index + 1;
    }
    return value.len;
}

fn skipOsc(value: []const u8, start: usize) usize {
    var index = start;
    while (index < value.len) : (index += 1) {
        if (value[index] == 0x07) return index + 1;
        if (value[index] == 0x1b and index + 1 < value.len and value[index + 1] == '\\') return index + 2;
    }
    return value.len;
}

fn dispatchAsync(allocator: std.mem.Allocator, caches: CacheSet, module_id: ModuleId, input: RenderInput) !AsyncRender {
    return switch (module_id) {
        .git_branch => fromGit(try caches.git_branch.renderAsync(allocator, input.cwd)),
        .language_versions => fromLanguageVersions(try caches.language_versions.renderAsync(allocator, input.cwd, input.env_hash, input.path_env)),
        else => .{ .pending = true },
    };
}

fn fromGit(rendered: git_branch_module.Cache.AsyncRender) AsyncRender {
    return .{ .segment = rendered.segment, .pending = rendered.pending };
}

fn fromLanguageVersions(rendered: language_versions_module.Cache.AsyncRender) AsyncRender {
    return .{ .segment = rendered.segment, .pending = rendered.pending };
}

fn dispatch(allocator: std.mem.Allocator, caches: CacheSet, module_id: ModuleId, input: RenderInput) !?[]u8 {
    return switch (module_id) {
        .cwd => try cwd_module.render(allocator, input.cwd, input.home, input.cwd_options),
        .git_branch => try caches.git_branch.render(allocator, input.cwd),
        .language_versions => try language_versions_module.probe(allocator, input.cwd, input.path_env),
        .time => try time_module.render(allocator, input.time, input.timestamp),
        .exit_status => try exit_status_module.render(allocator, input.exit),
        .jobs => try jobs_module.render(allocator, input.jobs),
        .cmd_duration => try cmd_duration_module.render(allocator, input.duration_ms, 1000),
        .user_host => try user_host_module.render(allocator, input.ssh, input.user, input.host),
        .cloud_ctx => try cloud_ctx_module.render(allocator, input.aws_profile, input.kubeconfig, input.home, caches.cloud_ctx, input.cloud_ctx),
        .cdhint => try cdhint_module.render(allocator, input.cwd, input.cdhint),
        .tmux_pane => try tmux_pane_module.render(allocator, input.tmux_pane, input.tmux_pane_options),
        .risk_tier => try risk_tier_module.render(allocator, .{ .aws = input.aws_profile }, if (input.ssh == null) null else input.host, null, input.risk_tier),
        .region_drift => try region_drift_module.render(allocator, input.home, input.aws_profile, input.aws_region, input.aws_default_region, input.cloudsdk_compute_region, input.azure_location, input.arm_location, input.azure_default_location),
        .cost_glance => try cost_glance_module.render(allocator, input.home),
        .vpn_status => try vpn_status_module.render(allocator),
        .ssh_target => try ssh_target_module.render(allocator, input.ssh, input.host, input.home),
        .container_provenance => try container_provenance_module.render(allocator),
        .sso_expiry => try sso_expiry_module.render(allocator, input.home, input.timestamp, input.sso_expiry),
        .iac_workspace => try iac_workspace_module.render(allocator, input.cwd, input.home),
    };
}

fn placeholderAlloc(allocator: std.mem.Allocator, module_id: ModuleId) ![]u8 {
    return std.fmt.allocPrint(allocator, "[pending:{s}]", .{moduleIdName(module_id)});
}

pub fn moduleIdName(module_id: ModuleId) []const u8 {
    return switch (module_id) {
        .cwd => "cwd",
        .git_branch => "git_branch",
        .language_versions => "language_versions",
        .time => "time",
        .exit_status => "exit_status",
        .jobs => "jobs",
        .cmd_duration => "cmd_duration",
        .user_host => "user_host",
        .cloud_ctx => "cloud_ctx",
        .cdhint => "cdhint",
        .tmux_pane => "tmux_pane",
        .risk_tier => "risk_tier",
        .region_drift => "region_drift",
        .cost_glance => "cost_glance",
        .vpn_status => "vpn_status",
        .ssh_target => "ssh_target",
        .container_provenance => "container_provenance",
        .sso_expiry => "sso_expiry",
        .iac_workspace => "iac_workspace",
    };
}

pub fn moduleIdFromName(name: []const u8) ?ModuleId {
    if (std.mem.eql(u8, name, "cwd")) return .cwd;
    if (std.mem.eql(u8, name, "git_branch")) return .git_branch;
    if (std.mem.eql(u8, name, "language_versions")) return .language_versions;
    if (std.mem.eql(u8, name, "time")) return .time;
    if (std.mem.eql(u8, name, "exit_status")) return .exit_status;
    if (std.mem.eql(u8, name, "jobs")) return .jobs;
    if (std.mem.eql(u8, name, "cmd_duration")) return .cmd_duration;
    if (std.mem.eql(u8, name, "user_host")) return .user_host;
    if (std.mem.eql(u8, name, "cloud_ctx")) return .cloud_ctx;
    if (std.mem.eql(u8, name, "cdhint")) return .cdhint;
    if (std.mem.eql(u8, name, "tmux_pane")) return .tmux_pane;
    if (std.mem.eql(u8, name, "risk_tier")) return .risk_tier;
    if (std.mem.eql(u8, name, "region_drift")) return .region_drift;
    if (std.mem.eql(u8, name, "cost_glance")) return .cost_glance;
    if (std.mem.eql(u8, name, "vpn_status")) return .vpn_status;
    if (std.mem.eql(u8, name, "ssh_target")) return .ssh_target;
    if (std.mem.eql(u8, name, "container_provenance")) return .container_provenance;
    if (std.mem.eql(u8, name, "sso_expiry")) return .sso_expiry;
    if (std.mem.eql(u8, name, "iac_workspace")) return .iac_workspace;
    return null;
}

test "classifies module execution" {
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.cwd));
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.cdhint));
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.tmux_pane));
    try std.testing.expectEqual(ExecutionClass.async, executionClass(.git_branch));
    try std.testing.expectEqual(ExecutionClass.async, executionClass(.language_versions));
}

test "renders stable sync pipeline" {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .time, .execution_class = .sync },
        .{ .id = .exit_status, .execution_class = .sync },
        .{ .id = .jobs, .execution_class = .sync },
        .{ .id = .cmd_duration, .execution_class = .sync },
    };
    var rendered = try renderPipeline(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 2,
        .jobs = 1,
        .duration_ms = 1200,
        .time = true,
        .no_async = false,
        .timestamp = 3660,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("/tmp/project time:01:01 \x1b[31mexit:2\x1b[0m jobs:1 took:1.2s> ", rendered.prompt);
    try std.testing.expect(rendered.redraw_token == null);
}

test "renders rtl opt-in reversed segment order" {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .exit_status, .execution_class = .sync },
        .{ .id = .jobs, .execution_class = .sync },
    };
    var rendered = try renderPipeline(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 2,
        .jobs = 1,
        .duration_ms = 0,
        .time = false,
        .no_async = true,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
        .rtl = true,
        .rtl_reverse = true,
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("jobs:1 \x1b[31mexit:2\x1b[0m /tmp/project> ", rendered.prompt);
}

test "renders opt-in cdhint module" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-dispatcher-cdhint-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const marker_path = try std.fmt.allocPrint(allocator, "{s}/package.json", .{dir_path});
    defer allocator.free(marker_path);
    {
        var file = try std.fs.createFileAbsolute(marker_path, .{});
        defer file.close();
        try file.writeAll("{}");
    }

    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cdhint, .execution_class = .sync },
    };
    var rendered = try renderPipeline(allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = dir_path,
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .no_async = true,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(allocator);
    try std.testing.expectEqualStrings("cd:node> ", rendered.prompt);
}

test "renders opt-in tmux pane module" {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .tmux_pane, .execution_class = .sync },
    };
    var rendered = try renderPipeline(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .no_async = true,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
        .tmux_pane = "%7",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("tmux:%7> ", rendered.prompt);
}

test "renders segment pipeline without prompt terminator" {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .time, .execution_class = .sync },
        .{ .id = .cmd_duration, .execution_class = .sync },
    };
    var rendered = try renderSegments(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 1500,
        .time = true,
        .no_async = true,
        .timestamp = 3660,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("time:01:01 took:1.5s", rendered.prompt);
}

test "renders async placeholder and redraw token" {
    const dir_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-dispatcher-git-{x}", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(std.testing.allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .async },
    };
    var rendered = try renderPipeline(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = dir_path,
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .no_async = false,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    const expected = try std.fmt.allocPrint(std.testing.allocator, "{s} [pending:git_branch]> ", .{dir_path});
    defer std.testing.allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered.prompt);
    try std.testing.expectEqualStrings("pending", rendered.redraw_token.?);
}

test "no async renders git synchronously" {
    const dir_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-dispatcher-git-{x}", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(std.testing.allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .async },
    };
    var rendered = try renderPipeline(std.testing.allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = dir_path,
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .no_async = true,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    const expected = try std.fmt.allocPrint(std.testing.allocator, "{s} git:main> ", .{dir_path});
    defer std.testing.allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered.prompt);
    try std.testing.expect(rendered.redraw_token == null);
}

test "snapshots stable prompt segments" {
    const allocator = std.testing.allocator;
    const root_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-segment-snapshot-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(root_path);
    defer std.fs.cwd().deleteTree(root_path) catch {};

    const cwd_path = try std.fmt.allocPrint(allocator, "{s}/repo", .{root_path});
    defer allocator.free(cwd_path);
    const home_path = try std.fmt.allocPrint(allocator, "{s}/home", .{root_path});
    defer allocator.free(home_path);
    try std.fs.cwd().makePath(cwd_path);
    try std.fs.cwd().makePath(home_path);
    try runGit(allocator, cwd_path, &.{ "git", "init", "-b", "main" });

    const aws_dir = try std.fmt.allocPrint(allocator, "{s}/.aws", .{home_path});
    defer allocator.free(aws_dir);
    try std.fs.cwd().makePath(aws_dir);
    const aws_config = try std.fmt.allocPrint(allocator, "{s}/config", .{aws_dir});
    defer allocator.free(aws_config);
    {
        var file = try std.fs.createFileAbsolute(aws_config, .{});
        defer file.close();
        try file.writeAll("[profile prod]\nregion = us-east-1\n");
    }

    const cost_path = (try cost_glance_module.costCachePathAlloc(allocator, home_path)).?;
    defer allocator.free(cost_path);
    try cost_glance_module.writeCostCache(allocator, cost_path, &.{
        .{ .provider = "aws", .amount = "1.2", .unit = "USD", .updated = 10 },
    }, 10);

    const sso_dir = try std.fmt.allocPrint(allocator, "{s}/.cache/shisa", .{home_path});
    defer allocator.free(sso_dir);
    try std.fs.cwd().makePath(sso_dir);
    const op_status = try std.fmt.allocPrint(allocator, "{s}/op-signin-status.json", .{sso_dir});
    defer allocator.free(op_status);
    {
        var file = try std.fs.createFileAbsolute(op_status, .{});
        defer file.close();
        try file.writeAll("{\"session\":{\"expires_in\":1200}}");
    }

    const terraform_dir = try std.fmt.allocPrint(allocator, "{s}/.terraform", .{cwd_path});
    defer allocator.free(terraform_dir);
    try std.fs.cwd().makePath(terraform_dir);
    const terraform_env = try std.fmt.allocPrint(allocator, "{s}/environment", .{terraform_dir});
    defer allocator.free(terraform_env);
    {
        var file = try std.fs.createFileAbsolute(terraform_env, .{});
        defer file.close();
        try file.writeAll("prod\n");
    }
    const terraform_lock = try std.fmt.allocPrint(allocator, "{s}/.terraform.tfstate.lock.info", .{cwd_path});
    defer allocator.free(terraform_lock);
    {
        var file = try std.fs.createFileAbsolute(terraform_lock, .{});
        defer file.close();
        try file.writeAll("{}");
    }

    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .sync },
        .{ .id = .time, .execution_class = .sync },
        .{ .id = .exit_status, .execution_class = .sync },
        .{ .id = .jobs, .execution_class = .sync },
        .{ .id = .cmd_duration, .execution_class = .sync },
        .{ .id = .user_host, .execution_class = .sync },
        .{ .id = .cloud_ctx, .execution_class = .sync },
        .{ .id = .risk_tier, .execution_class = .sync },
        .{ .id = .sso_expiry, .execution_class = .sync },
        .{ .id = .iac_workspace, .execution_class = .sync },
        .{ .id = .region_drift, .execution_class = .sync },
        .{ .id = .cost_glance, .execution_class = .sync },
        .{ .id = .ssh_target, .execution_class = .sync },
    };
    var rendered = try renderPipeline(allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = cwd_path,
        .home = home_path,
        .exit = 2,
        .jobs = 2,
        .duration_ms = 1500,
        .time = true,
        .no_async = true,
        .timestamp = 3660,
        .ssh = "192.0.2.1 55555 198.51.100.2 22",
        .user = "u",
        .host = "prod-bastion",
        .aws_profile = "prod",
        .aws_region = "us-west-2",
    }, pipeline[0..]);
    defer rendered.deinit(allocator);

    const expected = try std.fmt.allocPrint(
        allocator,
        "{s} git:main* time:01:01 \x1b[31mexit:2\x1b[0m jobs:2 took:1.5s u@prod-bastion cloud[aws:prod] risk:!prod sso[op:20m] iac[tf:prod!] region[aws:us-west-2!=us-east-1] cost[aws:$1.20] \xe2\x86\x92 prod-bastion (prod)> ",
        .{cwd_path},
    );
    defer allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered.prompt);
}

const PromptFixtureKind = enum {
    clean,
    dirty,
    conflict,
    prod,
    rtl,
};

const PromptFixture = struct {
    name: []const u8,
    kind: PromptFixtureKind,
};

test "snapshots prompt fixture corpus" {
    const allocator = std.testing.allocator;
    const root_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-prompt-fixtures-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(root_path);
    defer std.fs.cwd().deleteTree(root_path) catch {};

    const fixtures = [_]PromptFixture{
        .{ .name = "clean", .kind = .clean },
        .{ .name = "dirty", .kind = .dirty },
        .{ .name = "conflict", .kind = .conflict },
        .{ .name = "prod", .kind = .prod },
        .{ .name = "rtl", .kind = .rtl },
    };

    for (fixtures) |fixture| {
        const actual = try renderPromptFixtureAlloc(allocator, root_path, fixture);
        defer allocator.free(actual);
        const normalized = try normalizePromptSnapshotAlloc(allocator, actual, root_path);
        defer allocator.free(normalized);
        const path = try std.fmt.allocPrint(allocator, "test/snapshots/prompt/{s}.txt", .{fixture.name});
        defer allocator.free(path);
        try expectOrUpdatePromptSnapshot(allocator, path, normalized);
    }
}

test "module names are public for diagnostics" {
    try std.testing.expectEqualStrings("language_versions", moduleIdName(.language_versions));
    try std.testing.expectEqual(ModuleId.cdhint, moduleIdFromName("cdhint").?);
    try std.testing.expectEqual(ModuleId.tmux_pane, moduleIdFromName("tmux_pane").?);
    try std.testing.expect(moduleIdFromName("missing") == null);
}

test "calculates filler width from visible cells" {
    try std.testing.expectEqual(@as(usize, 4), fillerWidth("cwd", "git", 10));
    try std.testing.expectEqual(@as(usize, 0), fillerWidth("left", "right", 4));
    try std.testing.expectEqual(@as(usize, 6), fillerWidth("\x1b[31merr\x1b[0m", "ok", 11));
    try std.testing.expectEqual(@as(usize, 6), fillerWidth("\x1b]7;file://host/tmp\x07cwd", "ok", 11));
}

test "renders right-aligned layout line" {
    const line = try renderAlignedLineAlloc(std.testing.allocator, "cwd", "time", 12);
    defer std.testing.allocator.free(line);
    try std.testing.expectEqualStrings("cwd     time", line);
    try std.testing.expectEqual(@as(usize, 12), visibleWidth(line));
}

test "right-aligns through control sequences" {
    const line = try renderAlignedLineAlloc(std.testing.allocator, "\x1b[32mcwd\x1b[0m", "ok", 8);
    defer std.testing.allocator.free(line);
    try std.testing.expectEqualStrings("\x1b[32mcwd\x1b[0m   ok", line);
    try std.testing.expectEqual(@as(usize, 8), visibleWidth(line));
}

test "snapshots layout shapes" {
    try expectLayoutSnapshot("left-only", &.{.{ .left = "cwd git" }}, 16);
    try expectLayoutSnapshot("right-aligned", &.{.{ .left = "cwd", .right = "time" }}, 12);
    try expectLayoutSnapshot("multi-line", &.{
        .{ .left = "cwd", .right = "time" },
        .{ .left = "exit:2", .right = "jobs:1" },
    }, 16);
    try expectLayoutSnapshot("cjk-width", &.{
        .{ .left = "\xe9\xa1\xb9\xe7\x9b\xae", .right = "\xe9\x80\x80\xe5\x87\xba 1" },
        .{ .left = "\xe3\x83\x97\xe3\x83\xad\xe3\x82\xb8\xe3\x82\xa7\xe3\x82\xaf\xe3\x83\x88", .right = "\xe7\xb5\x82\xe4\xba\x86 1" },
        .{ .left = "\xed\x94\x84\xeb\xa1\x9c\xec\xa0\x9d\xed\x8a\xb8", .right = "\xec\xa2\x85\xeb\xa3\x8c 1" },
    }, 20);
}

test "counts unicode glyphs as one visible cell for layout filler" {
    try std.testing.expectEqual(@as(usize, 3), visibleWidth("a→b"));
}

test "counts East Asian wide cells for layout filler" {
    try std.testing.expectEqual(@as(usize, 3), visibleWidth("\xe7\x95\x8ca"));
    try std.testing.expectEqual(@as(usize, 4), fillerWidth("\xe7\x95\x8c", "\xef\xbd\x81", 8));
    try std.testing.expectEqual(@as(usize, 3), visibleWidth("a\xc2\xb7b"));
}

const LocaleFixtureFile = struct {
    locale_fixtures: []LocaleFixture,
};

const LocaleFixture = struct {
    locale: []const u8 = "",
    language: []const u8 = "",
    direction: []const u8 = "",
    cwd: []const u8 = "",
    risk_tier: []const u8 = "",
    exit_status: []const u8 = "",
    branch: []const u8 = "",
};

test "renders RTL locale fixture strings without layout corruption" {
    var parsed = try readLocaleFixtures(std.testing.allocator, "test/fixtures/i18n/rtl.json");
    defer parsed.deinit();
    try std.testing.expectEqual(@as(usize, 3), parsed.value.locale_fixtures.len);
    for (parsed.value.locale_fixtures) |fixture| {
        try std.testing.expectEqualStrings("rtl", fixture.direction);
        const line = try renderAlignedLineAlloc(std.testing.allocator, fixture.cwd, fixture.exit_status, 24);
        defer std.testing.allocator.free(line);
        try std.testing.expectEqual(@as(usize, 24), visibleWidth(line));
        try std.testing.expect(std.mem.indexOf(u8, line, fixture.cwd) != null);
        try std.testing.expect(std.mem.indexOf(u8, line, fixture.exit_status) != null);
    }
}

test "renders CJK locale fixture strings with East Asian widths" {
    var parsed = try readLocaleFixtures(std.testing.allocator, "test/fixtures/i18n/cjk.json");
    defer parsed.deinit();
    try std.testing.expectEqual(@as(usize, 3), parsed.value.locale_fixtures.len);
    for (parsed.value.locale_fixtures) |fixture| {
        try std.testing.expectEqualStrings("ltr", fixture.direction);
        const line = try renderAlignedLineAlloc(std.testing.allocator, fixture.cwd, fixture.exit_status, 20);
        defer std.testing.allocator.free(line);
        try std.testing.expectEqual(@as(usize, 20), visibleWidth(line));
        try std.testing.expect(std.mem.indexOf(u8, line, fixture.cwd) != null);
        try std.testing.expect(std.mem.indexOf(u8, line, fixture.exit_status) != null);
    }
}

fn readLocaleFixtures(allocator: std.mem.Allocator, path: []const u8) !std.json.Parsed(LocaleFixtureFile) {
    const source = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024);
    defer allocator.free(source);
    return std.json.parseFromSlice(LocaleFixtureFile, allocator, source, .{ .ignore_unknown_fields = true, .allocate = .alloc_always });
}

fn expectLayoutSnapshot(name: []const u8, lines: []const LayoutLineInput, cols: u16) !void {
    const actual = try renderLayoutLinesAlloc(std.testing.allocator, lines, cols);
    defer std.testing.allocator.free(actual);
    const path = try std.fmt.allocPrint(std.testing.allocator, "test/snapshots/layout/{s}.txt", .{name});
    defer std.testing.allocator.free(path);
    const expected = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(expected);
    try std.testing.expectEqualStrings(expected, actual);
}

fn renderPromptFixtureAlloc(allocator: std.mem.Allocator, root_path: []const u8, fixture: PromptFixture) ![]u8 {
    const cwd_path = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ root_path, fixture.name });
    defer allocator.free(cwd_path);
    const home_path = try std.fmt.allocPrint(allocator, "{s}/home-{s}", .{ root_path, fixture.name });
    defer allocator.free(home_path);
    try setupPromptFixture(allocator, cwd_path, home_path, fixture.kind);

    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(allocator);

    const base_pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .sync },
        .{ .id = .exit_status, .execution_class = .sync },
        .{ .id = .jobs, .execution_class = .sync },
        .{ .id = .cmd_duration, .execution_class = .sync },
    };
    const prod_pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .sync },
        .{ .id = .time, .execution_class = .sync },
        .{ .id = .exit_status, .execution_class = .sync },
        .{ .id = .jobs, .execution_class = .sync },
        .{ .id = .cmd_duration, .execution_class = .sync },
        .{ .id = .user_host, .execution_class = .sync },
        .{ .id = .cloud_ctx, .execution_class = .sync },
        .{ .id = .risk_tier, .execution_class = .sync },
        .{ .id = .sso_expiry, .execution_class = .sync },
        .{ .id = .iac_workspace, .execution_class = .sync },
        .{ .id = .region_drift, .execution_class = .sync },
        .{ .id = .cost_glance, .execution_class = .sync },
        .{ .id = .ssh_target, .execution_class = .sync },
    };

    const is_prod = fixture.kind == .prod;
    const is_rtl = fixture.kind == .rtl;
    var rendered = try renderPipeline(allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = cwd_path,
        .home = home_path,
        .exit = if (fixture.kind == .conflict or is_prod or is_rtl) 2 else 0,
        .jobs = if (is_prod) 2 else if (is_rtl) 1 else 0,
        .duration_ms = if (is_prod or is_rtl) 1500 else 0,
        .time = is_prod,
        .no_async = true,
        .timestamp = 3660,
        .ssh = if (is_prod) "192.0.2.1 55555 198.51.100.2 22" else null,
        .user = "u",
        .host = if (is_prod) "prod-bastion" else "h",
        .aws_profile = if (is_prod) "prod" else null,
        .aws_region = if (is_prod) "us-west-2" else null,
        .rtl = is_rtl,
        .rtl_reverse = is_rtl,
    }, if (is_prod) prod_pipeline[0..] else base_pipeline[0..]);
    defer rendered.deinit(allocator);
    return allocator.dupe(u8, rendered.prompt);
}

fn setupPromptFixture(allocator: std.mem.Allocator, cwd_path: []const u8, home_path: []const u8, kind: PromptFixtureKind) !void {
    try std.fs.cwd().makePath(cwd_path);
    try std.fs.cwd().makePath(home_path);
    try runGit(allocator, cwd_path, &.{ "git", "init", "-b", "main" });
    switch (kind) {
        .clean => {},
        .dirty => try writeFileAbsoluteAlloc(allocator, cwd_path, "dirty.txt", "dirty\n"),
        .conflict => try setupConflictFixture(allocator, cwd_path),
        .prod => try setupProdFixture(allocator, cwd_path, home_path),
        .rtl => {},
    }
}

fn setupConflictFixture(allocator: std.mem.Allocator, cwd_path: []const u8) !void {
    try writeFileAbsoluteAlloc(allocator, cwd_path, "conflict.txt", "base\n");
    try runGit(allocator, cwd_path, &.{ "git", "add", "conflict.txt" });
    try runGitCommit(allocator, cwd_path, "base", false);
    try runGit(allocator, cwd_path, &.{ "git", "checkout", "-b", "side" });
    try writeFileAbsoluteAlloc(allocator, cwd_path, "conflict.txt", "side\n");
    try runGitCommit(allocator, cwd_path, "side", true);
    try runGit(allocator, cwd_path, &.{ "git", "checkout", "main" });
    try writeFileAbsoluteAlloc(allocator, cwd_path, "conflict.txt", "main\n");
    try runGitCommit(allocator, cwd_path, "main", true);
    try runGitExpectFailure(allocator, cwd_path, &.{ "git", "merge", "side" });
}

fn setupProdFixture(allocator: std.mem.Allocator, cwd_path: []const u8, home_path: []const u8) !void {
    const aws_dir = try std.fmt.allocPrint(allocator, "{s}/.aws", .{home_path});
    defer allocator.free(aws_dir);
    try std.fs.cwd().makePath(aws_dir);
    try writeFileAbsoluteAlloc(allocator, aws_dir, "config", "[profile prod]\nregion = us-east-1\n");

    const cost_path = (try cost_glance_module.costCachePathAlloc(allocator, home_path)).?;
    defer allocator.free(cost_path);
    try cost_glance_module.writeCostCache(allocator, cost_path, &.{
        .{ .provider = "aws", .amount = "1.2", .unit = "USD", .updated = 10 },
    }, 10);

    const sso_dir = try std.fmt.allocPrint(allocator, "{s}/.cache/shisa", .{home_path});
    defer allocator.free(sso_dir);
    try std.fs.cwd().makePath(sso_dir);
    try writeFileAbsoluteAlloc(allocator, sso_dir, "op-signin-status.json", "{\"session\":{\"expires_in\":1200}}");

    const terraform_dir = try std.fmt.allocPrint(allocator, "{s}/.terraform", .{cwd_path});
    defer allocator.free(terraform_dir);
    try std.fs.cwd().makePath(terraform_dir);
    try writeFileAbsoluteAlloc(allocator, terraform_dir, "environment", "prod\n");
    try writeFileAbsoluteAlloc(allocator, cwd_path, ".terraform.tfstate.lock.info", "{}");
}

fn writeFileAbsoluteAlloc(allocator: std.mem.Allocator, dir_path: []const u8, name: []const u8, contents: []const u8) !void {
    const path = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ dir_path, name });
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{});
    defer file.close();
    try file.writeAll(contents);
}

fn normalizePromptSnapshotAlloc(allocator: std.mem.Allocator, prompt: []const u8, root_path: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var index: usize = 0;
    while (index < prompt.len) {
        if (std.mem.startsWith(u8, prompt[index..], root_path)) {
            try out.appendSlice(allocator, "<root>");
            index += root_path.len;
            continue;
        }
        switch (prompt[index]) {
            0x1b => try out.appendSlice(allocator, "\\x1b"),
            0x07 => try out.appendSlice(allocator, "\\x07"),
            '\n' => try out.appendSlice(allocator, "\\n\n"),
            0x80...0xff => try std.fmt.format(out.writer(allocator), "\\x{x:0>2}", .{prompt[index]}),
            else => try out.append(allocator, prompt[index]),
        }
        index += 1;
    }
    try out.append(allocator, '\n');
    return out.toOwnedSlice(allocator);
}

fn expectOrUpdatePromptSnapshot(allocator: std.mem.Allocator, path: []const u8, actual: []const u8) !void {
    const token = std.process.getEnvVarOwned(allocator, "SHISA_UPDATE_SNAPSHOTS") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (token) |value| allocator.free(value);

    if (token) |value| {
        if (std.mem.eql(u8, value, "update-snapshots")) {
            if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
            var file = try std.fs.cwd().createFile(path, .{ .truncate = true });
            defer file.close();
            try file.writeAll(actual);
            return;
        }
    }

    const expected = try std.fs.cwd().readFileAlloc(allocator, path, 4096);
    defer allocator.free(expected);
    try std.testing.expectEqualStrings(expected, actual);
}

fn runGit(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.testing.expect(switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    });
}

fn runGitCommit(allocator: std.mem.Allocator, cwd_path: []const u8, message: []const u8, all: bool) !void {
    if (all) {
        return runGit(allocator, cwd_path, &.{ "git", "-c", "user.email=shisa@example.invalid", "-c", "user.name=Shisa Test", "-c", "commit.gpgsign=false", "commit", "-am", message });
    }
    return runGit(allocator, cwd_path, &.{ "git", "-c", "user.email=shisa@example.invalid", "-c", "user.name=Shisa Test", "-c", "commit.gpgsign=false", "commit", "-m", message });
}

fn runGitExpectFailure(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.testing.expect(switch (result.term) {
        .Exited => |code| code != 0,
        else => false,
    });
}
