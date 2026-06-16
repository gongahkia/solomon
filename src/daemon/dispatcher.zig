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

const default_pipeline = [_]ModuleId{ .cwd, .git_branch, .time, .exit_status, .jobs, .cmd_duration, .user_host };

pub fn executionClass(module_id: ModuleId) ExecutionClass {
    return switch (module_id) {
        .git_branch => .cached,
        else => .sync,
    };
}

pub fn renderDefault(allocator: std.mem.Allocator, git_branch_cache: *git_branch_module.Cache, input: RenderInput) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var wrote_segment = false;

    for (default_pipeline) |module_id| {
        const segment = try dispatch(allocator, git_branch_cache, module_id, input);
        defer if (segment) |value| allocator.free(value);
        if (segment) |value| {
            if (wrote_segment) try out.append(allocator, ' ');
            try out.appendSlice(allocator, value);
            wrote_segment = true;
        }
    }

    try out.appendSlice(allocator, "> ");
    return out.toOwnedSlice(allocator);
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

test "classifies module execution" {
    try std.testing.expectEqual(ExecutionClass.sync, executionClass(.cwd));
    try std.testing.expectEqual(ExecutionClass.cached, executionClass(.git_branch));
}

test "renders default pipeline" {
    var cache = git_branch_module.Cache{};
    defer cache.deinit(std.testing.allocator);
    const prompt = try renderDefault(std.testing.allocator, &cache, .{
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
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings("/tmp/project time:01:01 \x1b[31mexit:2\x1b[0m jobs:1 took:1.2s> ", prompt);
}
