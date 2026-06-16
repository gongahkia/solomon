const std = @import("std");

pub const Cache = struct {
    valid: bool = false,
    cwd: ?[]u8 = null,
    segment: ?[]u8 = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn render(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
        if (self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path)) {
            if (self.segment) |segment| return try allocator.dupe(u8, segment);
            return null;
        }

        self.clear(allocator);
        self.valid = true;
        self.cwd = try allocator.dupe(u8, cwd_path);
        self.segment = try probe(allocator, cwd_path);

        if (self.segment) |segment| return try allocator.dupe(u8, segment);
        return null;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.cwd) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.* = .{};
    }
};

fn probe(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    const branch_result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "branch", "--show-current" },
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(branch_result.stdout);
    defer allocator.free(branch_result.stderr);

    if (!exitedZero(branch_result.term)) return null;

    const branch = std.mem.trim(u8, branch_result.stdout, " \t\r\n");
    if (branch.len == 0) return null;

    const dirty = try isDirty(allocator, cwd_path);
    return try std.fmt.allocPrint(allocator, "git:{s}{s}", .{ branch, if (dirty) "*" else "" });
}

fn isDirty(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const status_result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "status", "--porcelain" },
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return false;
    defer allocator.free(status_result.stdout);
    defer allocator.free(status_result.stderr);

    return exitedZero(status_result.term) and std.mem.trim(u8, status_result.stdout, " \t\r\n").len > 0;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
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
    try std.testing.expect(exitedZero(result.term));
}

test "hides outside git repo" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{};
    defer cache.deinit(allocator);
    try std.testing.expect(try cache.render(allocator, dir_path) == null);
}

test "renders branch and dirty indicator" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    var cache = Cache{};
    defer cache.deinit(allocator);
    const rendered = (try cache.render(allocator, dir_path)).?;
    defer allocator.free(rendered);
    try std.testing.expectEqualStrings("git:main*", rendered);
}
