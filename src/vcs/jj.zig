const std = @import("std");

pub fn findRoot(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_jj = try std.fs.path.join(allocator, &.{ current, ".jj" });
        const found = found: {
            std.fs.cwd().access(dot_jj, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(dot_jj);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(dot_jj);
        if (found) return current;

        const parent = std.fs.path.dirname(current) orelse {
            allocator.free(current);
            break;
        };
        if (std.mem.eql(u8, parent, current)) {
            allocator.free(current);
            break;
        }
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }

    return null;
}

pub fn isRepo(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const root = try findRoot(allocator, cwd_path);
    if (root) |path| {
        allocator.free(path);
        return true;
    }
    return false;
}

test "detects jj repo in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_jj = try std.fmt.allocPrint(allocator, "{s}/.jj", .{dir_path});
    defer allocator.free(dot_jj);
    try std.fs.cwd().makePath(dot_jj);

    const root = (try findRoot(allocator, dir_path)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
    try std.testing.expect(try isRepo(allocator, dir_path));
}

test "detects jj repo from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_jj = try std.fmt.allocPrint(allocator, "{s}/.jj", .{dir_path});
    defer allocator.free(dot_jj);
    try std.fs.cwd().makePath(dot_jj);

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    const root = (try findRoot(allocator, nested)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
}

test "ignores non jj directories" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect(!(try isRepo(allocator, dir_path)));
    try std.testing.expect((try findRoot(allocator, dir_path)) == null);
}
