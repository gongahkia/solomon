const std = @import("std");

pub const module_id = "vcs_stack";

pub const Provider = enum {
    graphite,

    pub fn label(self: Provider) []const u8 {
        return switch (self) {
            .graphite => "graphite",
        };
    }
};

pub const Detection = struct {
    provider: Provider,
    root_path: []u8,
    marker_path: []u8,

    pub fn deinit(self: *Detection, allocator: std.mem.Allocator) void {
        allocator.free(self.root_path);
        allocator.free(self.marker_path);
        self.* = undefined;
    }
};

pub fn detect(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    if (try findMarkerRoot(allocator, cwd_path, ".graphite_repo_config")) |root| {
        errdefer allocator.free(root);
        const marker_path = try std.fs.path.join(allocator, &.{ root, ".graphite_repo_config" });
        return .{
            .provider = .graphite,
            .root_path = root,
            .marker_path = marker_path,
        };
    }
    return null;
}

pub fn isGraphiteStack(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const found = try findMarkerRoot(allocator, cwd_path, ".graphite_repo_config");
    if (found) |root| {
        allocator.free(root);
        return true;
    }
    return false;
}

fn findMarkerRoot(allocator: std.mem.Allocator, cwd_path: []const u8, marker_name: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const marker_path = try std.fs.path.join(allocator, &.{ current, marker_name });
        const found = found: {
            std.fs.cwd().access(marker_path, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(marker_path);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(marker_path);
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

test "detects graphite stack in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "{}\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.graphite, detection.provider);
    try std.testing.expectEqualStrings("graphite", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isGraphiteStack(allocator, dir_path));
}

test "detects graphite stack from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "{}\n");

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    var detection = (try detect(allocator, nested)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.graphite, detection.provider);
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
}

test "ignores directories without stack metadata" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect((try detect(allocator, dir_path)) == null);
    try std.testing.expect(!(try isGraphiteStack(allocator, dir_path)));
}

fn writeFile(path: []const u8, contents: []const u8) !void {
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(contents);
}
