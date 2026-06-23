const std = @import("std");
const cli_util = @import("util.zig");
const vcs_worktree = @import("vcs_worktree");

pub const Config = struct {
    cwd: ?[]const u8 = null,
};

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseArgs(args);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const output = try outputAlloc(allocator, cwd);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseArgs(args: []const []const u8) !Config {
    var config = Config{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownWorktreesArgument;
        }
    }
    return config;
}

fn outputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    const active_root_output = cli_util.gitOutputAlloc(allocator, cwd_path, &.{ "git", "rev-parse", "--show-toplevel" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(active_root_output);
    const active_root = std.mem.trim(u8, active_root_output, " \t\r\n");

    const porcelain = cli_util.gitOutputAlloc(allocator, cwd_path, &.{ "git", "worktree", "list", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(porcelain);

    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    try markDirty(allocator, &list);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn renderAlloc(allocator: std.mem.Allocator, porcelain: []const u8, active_root: []const u8) ![]u8 {
    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn markDirty(allocator: std.mem.Allocator, list: *vcs_worktree.List) !void {
    for (list.entries) |*entry| {
        entry.dirty = try statusDirty(allocator, entry.path);
    }
}

fn statusDirty(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const output = cli_util.gitOutputAlloc(allocator, cwd_path, &.{ "git", "status", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(output);
    return std.mem.trim(u8, output, " \t\r\n").len != 0;
}

test "worktrees args parse cwd override" {
    const config = try parseArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownWorktreesArgument, parseArgs(&.{"--bad"}));
}

test "worktrees output marks active path" {
    const source =
        \\worktree /repo
        \\HEAD a
        \\branch refs/heads/main
        \\
        \\worktree /repo-linked
        \\HEAD b
        \\branch refs/heads/feature
        \\
    ;
    const output = try renderAlloc(std.testing.allocator, source, "/repo-linked");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("  /repo main\n* /repo-linked feature\n", output);
}
