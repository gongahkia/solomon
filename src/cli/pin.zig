const std = @import("std");
const cli_util = @import("util.zig");

pub fn pinCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownPinArgument;
    const path = try std.fs.cwd().realpathAlloc(allocator, args[0]);
    defer allocator.free(path);
    const pins_path = try pinsPath(allocator);
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, path);

    const message = try std.fmt.allocPrint(allocator, "pinned {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn pinsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/pins", .{dir});
}

fn appendPin(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !void {
    if (std.fs.path.dirname(pins_path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    if (try pinExists(allocator, pins_path, path)) return;

    var file = try std.fs.createFileAbsolute(pins_path, .{ .truncate = false, .read = true });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(path);
    try file.writeAll("\n");
}

fn pinExists(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, pins_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        if (std.mem.eql(u8, line, path)) return true;
    }
    return false;
}

test "appends pin once" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-pin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const pins_path = try std.fmt.allocPrint(allocator, "{s}/pins", .{dir_path});
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, "/tmp/repo");
    try appendPin(allocator, pins_path, "/tmp/repo");

    const contents = try std.fs.cwd().readFileAlloc(allocator, pins_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("/tmp/repo\n", contents);
}
