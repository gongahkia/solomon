const std = @import("std");
const cli_util = @import("util.zig");
const vcs_stack = @import("../vcs/stack.zig");

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
            return error.UnknownStackArgument;
        }
    }
    return config;
}

fn outputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var detection = (try vcs_stack.detect(allocator, cwd_path)) orelse {
        try out.appendSlice(allocator, "stack: none\n");
        return out.toOwnedSlice(allocator);
    };
    defer detection.deinit(allocator);

    try cli_util.appendFmt(allocator, &out, "provider: {s}\n", .{detection.provider.label()});
    try cli_util.appendFmt(allocator, &out, "root: {s}\n", .{detection.root_path});
    try cli_util.appendFmt(allocator, &out, "marker: {s}\n", .{detection.marker_path});
    if (detection.branch_name) |branch_name| {
        try cli_util.appendFmt(allocator, &out, "branch: {s}\n", .{branch_name});
    }
    return out.toOwnedSlice(allocator);
}

test "stack args parse cwd override" {
    const config = try parseArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownStackArgument, parseArgs(&.{"--bad"}));
}

test "stack output reports no stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const output = try outputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("stack: none\n", output);
}

test "stack output dumps detected stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    var file = try std.fs.createFileAbsolute(marker_path, .{});
    try file.writeAll("{}\n");
    file.close();

    const output = try outputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "provider: graphite\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, dir_path) != null);
    try std.testing.expect(std.mem.indexOf(u8, output, marker_path) != null);
}
