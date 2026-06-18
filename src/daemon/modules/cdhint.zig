const std = @import("std");

pub const Kind = enum {
    node,
    rust,
    python,
    go,

    pub fn label(self: Kind) []const u8 {
        return switch (self) {
            .node => "node",
            .rust => "rust",
            .python => "python",
            .go => "go",
        };
    }
};

pub const Project = struct {
    kind: Kind,
    root: []u8,
    marker: []const u8,

    pub fn deinit(self: *Project, allocator: std.mem.Allocator) void {
        allocator.free(self.root);
        self.* = undefined;
    }
};

const Rule = struct {
    marker: []const u8,
    kind: Kind,
};

const rules = [_]Rule{
    .{ .marker = "package.json", .kind = .node },
    .{ .marker = "Cargo.toml", .kind = .rust },
    .{ .marker = "pyproject.toml", .kind = .python },
    .{ .marker = "requirements.txt", .kind = .python },
    .{ .marker = "setup.py", .kind = .python },
    .{ .marker = "go.mod", .kind = .go },
};

pub fn detectAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) !?Project {
    var current = try allocator.dupe(u8, cwd_path);
    defer allocator.free(current);

    while (current.len > 0) {
        for (rules) |rule| {
            const marker_path = try std.fs.path.join(allocator, &.{ current, rule.marker });
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
            if (found) {
                return .{
                    .kind = rule.kind,
                    .root = try allocator.dupe(u8, current),
                    .marker = rule.marker,
                };
            }
        }

        const parent = std.fs.path.dirname(current) orelse break;
        if (std.mem.eql(u8, parent, current)) break;
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }
    return null;
}

test "detects direct node project marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cdhint-node-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const marker_path = try std.fmt.allocPrint(allocator, "{s}/package.json", .{dir_path});
    defer allocator.free(marker_path);
    try std.fs.cwd().writeFile(.{ .sub_path = marker_path, .data = "{}" });

    var project = (try detectAlloc(allocator, dir_path)).?;
    defer project.deinit(allocator);
    try std.testing.expectEqual(Kind.node, project.kind);
    try std.testing.expectEqualStrings("package.json", project.marker);
    try std.testing.expectEqualStrings(dir_path, project.root);
}

test "detects ancestor rust project marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cdhint-rust-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const child_path = try std.fmt.allocPrint(allocator, "{s}/src/bin", .{dir_path});
    defer allocator.free(child_path);
    try std.fs.cwd().makePath(child_path);
    const marker_path = try std.fmt.allocPrint(allocator, "{s}/Cargo.toml", .{dir_path});
    defer allocator.free(marker_path);
    try std.fs.cwd().writeFile(.{ .sub_path = marker_path, .data = "[package]\nname = \"demo\"\n" });

    var project = (try detectAlloc(allocator, child_path)).?;
    defer project.deinit(allocator);
    try std.testing.expectEqual(Kind.rust, project.kind);
    try std.testing.expectEqualStrings("Cargo.toml", project.marker);
    try std.testing.expectEqualStrings(dir_path, project.root);
}

test "ignores directories without project markers" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cdhint-empty-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try std.testing.expect(try detectAlloc(allocator, dir_path) == null);
}
