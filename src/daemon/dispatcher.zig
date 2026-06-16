const std = @import("std");
const cmd_duration_module = @import("modules/cmd_duration.zig");
const cwd_module = @import("modules/cwd.zig");
const exit_status_module = @import("modules/exit_status.zig");
const git_branch_module = @import("modules/git_branch.zig");
const jobs_module = @import("modules/jobs.zig");
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
    time,
    exit_status,
    jobs,
    cmd_duration,
    user_host,
};

pub const ModuleSpec = struct {
    id: ModuleId,
    execution_class: ExecutionClass,
};

pub const RenderedPrompt = struct {
    prompt: []u8,
    redraw_token: ?[]u8 = null,

    pub fn deinit(self: *RenderedPrompt, allocator: std.mem.Allocator) void {
        allocator.free(self.prompt);
        if (self.redraw_token) |token| allocator.free(token);
        self.* = undefined;
    }
};

pub const RenderInput = struct {
    cwd: []const u8,
    home: ?[]const u8,
    exit: i32,
    jobs: u32,
    duration_ms: u64,
    time: bool,
    timestamp: i64,
    ssh: ?[]const u8,
    user: []const u8,
    host: []const u8,
};

const default_pipeline = [_]ModuleSpec{
    .{ .id = .cwd, .execution_class = executionClass(.cwd) },
    .{ .id = .git_branch, .execution_class = executionClass(.git_branch) },
    .{ .id = .time, .execution_class = executionClass(.time) },
    .{ .id = .exit_status, .execution_class = executionClass(.exit_status) },
    .{ .id = .jobs, .execution_class = executionClass(.jobs) },
    .{ .id = .cmd_duration, .execution_class = executionClass(.cmd_duration) },
    .{ .id = .user_host, .execution_class = executionClass(.user_host) },
};

pub fn executionClass(module_id: ModuleId) ExecutionClass {
    return switch (module_id) {
        .git_branch => .cached,
        else => .sync,
    };
}

pub fn renderDefault(allocator: std.mem.Allocator, git_branch_cache: *git_branch_module.Cache, input: RenderInput) !RenderedPrompt {
    return renderPipeline(allocator, git_branch_cache, input, default_pipeline[0..]);
}

pub fn renderPipeline(allocator: std.mem.Allocator, git_branch_cache: *git_branch_module.Cache, input: RenderInput, pipeline: []const ModuleSpec) !RenderedPrompt {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var wrote_segment = false;
    var has_async = false;

    for (pipeline) |spec| {
        const segment = if (spec.execution_class == .async) async: {
            has_async = true;
            break :async try placeholderAlloc(allocator, spec.id);
        } else try dispatch(allocator, git_branch_cache, spec.id, input);
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
    };
}

fn dispatch(allocator: std.mem.Allocator, git_branch_cache: *git_branch_module.Cache, module_id: ModuleId, input: RenderInput) !?[]u8 {
    return switch (module_id) {
        .cwd => try cwd_module.render(allocator, input.cwd, input.home, 3),
        .git_branch => try git_branch_cache.render(allocator, input.cwd),
        .time => try time_module.render(allocator, input.time, input.timestamp),
        .exit_status => try exit_status_module.render(allocator, input.exit),
        .jobs => try jobs_module.render(allocator, input.jobs),
        .cmd_duration => try cmd_duration_module.render(allocator, input.duration_ms, 1000),
        .user_host => try user_host_module.render(allocator, input.ssh, input.user, input.host),
    };
}

fn placeholderAlloc(allocator: std.mem.Allocator, module_id: ModuleId) ![]u8 {
    return std.fmt.allocPrint(allocator, "[pending:{s}]", .{moduleIdName(module_id)});
}

fn moduleIdName(module_id: ModuleId) []const u8 {
    return switch (module_id) {
        .cwd => "cwd",
        .git_branch => "git_branch",
        .time => "time",
        .exit_status => "exit_status",
        .jobs => "jobs",
        .cmd_duration => "cmd_duration",
        .user_host => "user_host",
    };
}

test "classifies module execution" {
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.cwd));
    try std.testing.expectEqual(ExecutionClass.cached, executionClass(.git_branch));
}

test "renders default pipeline" {
    var cache = git_branch_module.Cache{};
    defer cache.deinit(std.testing.allocator);
    var rendered = try renderDefault(std.testing.allocator, &cache, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 2,
        .jobs = 1,
        .duration_ms = 1200,
        .time = true,
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
    var cache = git_branch_module.Cache{};
    defer cache.deinit(std.testing.allocator);
    const pipeline = [_]ModuleSpec{
        .{ .id = .cwd, .execution_class = .sync },
        .{ .id = .git_branch, .execution_class = .async },
    };
    var rendered = try renderPipeline(std.testing.allocator, &cache, .{
        .cwd = "/tmp/project",
        .home = null,
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .timestamp = 0,
        .ssh = null,
        .user = "u",
        .host = "h",
    }, pipeline[0..]);
    defer rendered.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("/tmp/project [pending:git_branch]> ", rendered.prompt);
    try std.testing.expectEqualStrings("pending", rendered.redraw_token.?);
}
