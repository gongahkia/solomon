const std = @import("std");
const cloud_ctx_module = @import("modules/cloud_ctx.zig");
const cmd_duration_module = @import("modules/cmd_duration.zig");
const cwd_module = @import("modules/cwd.zig");
const exit_status_module = @import("modules/exit_status.zig");
const git_branch_module = @import("modules/git_branch.zig");
const iac_workspace_module = @import("modules/iac_workspace.zig");
const jobs_module = @import("modules/jobs.zig");
const language_versions_module = @import("modules/language_versions.zig");
const sso_expiry_module = @import("modules/sso_expiry.zig");
const time_module = @import("modules/time.zig");
const user_host_module = @import("modules/user_host.zig");

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

    pub fn deinit(self: *RenderedPrompt, allocator: std.mem.Allocator) void {
        allocator.free(self.prompt);
        if (self.redraw_token) |token| allocator.free(token);
        self.* = undefined;
    }
};

pub const SlowWarning = struct {
    module_id: ModuleId,
    elapsed_ns: u64,
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
    aws_profile: ?[]const u8 = null,
    kubeconfig: ?[]const u8 = null,
    cloud_ctx: cloud_ctx_module.Options = .{},
    sso_expiry: sso_expiry_module.Options = .{},
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
    .{ .id = .sso_expiry, .execution_class = executionClass(.sso_expiry) },
    .{ .id = .iac_workspace, .execution_class = executionClass(.iac_workspace) },
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

pub fn renderPipeline(allocator: std.mem.Allocator, caches: CacheSet, input: RenderInput, pipeline: []const ModuleSpec) !RenderedPrompt {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var wrote_segment = false;
    var has_async = false;
    var slow_warning: ?SlowWarning = null;

    for (pipeline) |spec| {
        var async_result: ?AsyncRender = null;
        defer if (async_result) |*value| value.deinit(allocator);

        const start_ns = std.time.nanoTimestamp();
        const segment = if (spec.execution_class == .async and !input.no_async) async: {
            async_result = try dispatchAsync(allocator, caches, spec.id, input);
            if (async_result.?.pending) has_async = true;
            if (async_result.?.segment) |value| break :async try allocator.dupe(u8, value);
            if (async_result.?.pending) break :async try placeholderAlloc(allocator, spec.id);
            break :async null;
        } else try dispatch(allocator, caches, spec.id, input);
        const elapsed_ns = @as(u64, @intCast(std.time.nanoTimestamp() - start_ns));
        if (slow_warning == null and elapsed_ns > slow_warning_ns) {
            slow_warning = .{ .module_id = spec.id, .elapsed_ns = elapsed_ns };
        }
        defer if (segment) |value| allocator.free(value);
        if (segment) |value| {
            if (wrote_segment) try out.append(allocator, ' ');
            try out.appendSlice(allocator, value);
            wrote_segment = true;
        }
    }

    try out.appendSlice(allocator, "> ");
    return .{
        .prompt = try out.toOwnedSlice(allocator),
        .redraw_token = if (has_async) try allocator.dupe(u8, "pending") else null,
        .slow_warning = slow_warning,
    };
}

fn dispatchAsync(allocator: std.mem.Allocator, caches: CacheSet, module_id: ModuleId, input: RenderInput) !AsyncRender {
    return switch (module_id) {
        .git_branch => fromGit(try caches.git_branch.renderAsync(allocator, input.cwd)),
        .language_versions => fromLanguageVersions(try caches.language_versions.renderAsync(allocator, input.cwd)),
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
        .cwd => try cwd_module.render(allocator, input.cwd, input.home, 3),
        .git_branch => try caches.git_branch.render(allocator, input.cwd),
        .language_versions => try language_versions_module.probe(allocator, input.cwd),
        .time => try time_module.render(allocator, input.time, input.timestamp),
        .exit_status => try exit_status_module.render(allocator, input.exit),
        .jobs => try jobs_module.render(allocator, input.jobs),
        .cmd_duration => try cmd_duration_module.render(allocator, input.duration_ms, 1000),
        .user_host => try user_host_module.render(allocator, input.ssh, input.user, input.host),
        .cloud_ctx => try cloud_ctx_module.render(allocator, input.aws_profile, input.kubeconfig, input.home, caches.cloud_ctx, input.cloud_ctx),
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
        .sso_expiry => "sso_expiry",
        .iac_workspace => "iac_workspace",
    };
}

test "classifies module execution" {
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.cwd));
    try std.testing.expectEqual(ExecutionClass.async, executionClass(.git_branch));
    try std.testing.expectEqual(ExecutionClass.async, executionClass(.language_versions));
}

test "renders default pipeline" {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(std.testing.allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(std.testing.allocator);
    var cloud_cache = cloud_ctx_module.Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cloud_cache.deinit(std.testing.allocator);
    var rendered = try renderDefault(std.testing.allocator, .{
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
    });
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("/tmp/project time:01:01 \x1b[31mexit:2\x1b[0m jobs:1 took:1.2s> ", rendered.prompt);
    try std.testing.expect(rendered.redraw_token == null);
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
    var rendered = try renderDefault(std.testing.allocator, .{
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
    });
    defer rendered.deinit(std.testing.allocator);
    const expected = try std.fmt.allocPrint(std.testing.allocator, "{s} git:main> ", .{dir_path});
    defer std.testing.allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered.prompt);
    try std.testing.expect(rendered.redraw_token == null);
}

test "module names are public for diagnostics" {
    try std.testing.expectEqualStrings("language_versions", moduleIdName(.language_versions));
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
