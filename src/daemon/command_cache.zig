const std = @import("std");

pub const WatchedMtime = struct {
    path: []const u8,
    mtime_ns: i128,
};

pub const KeyInput = struct {
    cmd: []const u8,
    args: []const []const u8 = &.{},
    cwd: []const u8,
    mtimes: []const WatchedMtime = &.{},
};

pub fn keyAlloc(allocator: std.mem.Allocator, input: KeyInput) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    const sorted_mtimes = try allocator.dupe(WatchedMtime, input.mtimes);
    defer allocator.free(sorted_mtimes);
    std.mem.sort(WatchedMtime, sorted_mtimes, {}, lessThanWatchedMtime);

    try appendString(allocator, &out, "cmd", input.cmd);
    try appendInt(allocator, &out, "argc", input.args.len);
    for (input.args) |arg| try appendString(allocator, &out, "arg", arg);
    try appendString(allocator, &out, "cwd", input.cwd);
    try appendInt(allocator, &out, "mtimec", sorted_mtimes.len);
    for (sorted_mtimes) |mtime| {
        try appendString(allocator, &out, "path", mtime.path);
        try appendInt(allocator, &out, "mtime", mtime.mtime_ns);
    }

    return out.toOwnedSlice(allocator);
}

fn lessThanWatchedMtime(_: void, a: WatchedMtime, b: WatchedMtime) bool {
    if (std.mem.eql(u8, a.path, b.path)) return a.mtime_ns < b.mtime_ns;
    return std.mem.lessThan(u8, a.path, b.path);
}

fn appendString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: []const u8) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}:", .{value.len});
    try out.appendSlice(allocator, value);
    try out.append(allocator, '|');
}

fn appendInt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: anytype) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}", .{value});
    try out.append(allocator, '|');
}

test "keys include command args cwd and mtimes" {
    const allocator = std.testing.allocator;
    const base = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(base);
    const changed_arg = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"-V"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(changed_arg);
    const changed_cwd = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/other",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(changed_cwd);
    const changed_mtime = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 11 }},
    });
    defer allocator.free(changed_mtime);

    try std.testing.expect(!std.mem.eql(u8, base, changed_arg));
    try std.testing.expect(!std.mem.eql(u8, base, changed_cwd));
    try std.testing.expect(!std.mem.eql(u8, base, changed_mtime));
}

test "mtime key order is deterministic" {
    const allocator = std.testing.allocator;
    const first = try keyAlloc(allocator, .{
        .cmd = "node",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{
            .{ .path = "/repo/package.json", .mtime_ns = 2 },
            .{ .path = "/repo/.node-version", .mtime_ns = 1 },
        },
    });
    defer allocator.free(first);
    const second = try keyAlloc(allocator, .{
        .cmd = "node",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{
            .{ .path = "/repo/.node-version", .mtime_ns = 1 },
            .{ .path = "/repo/package.json", .mtime_ns = 2 },
        },
    });
    defer allocator.free(second);

    try std.testing.expectEqualStrings(first, second);
}

test "length prefixes prevent separator collisions" {
    const allocator = std.testing.allocator;
    const first = try keyAlloc(allocator, .{ .cmd = "ab", .args = &.{"c"}, .cwd = "/repo" });
    defer allocator.free(first);
    const second = try keyAlloc(allocator, .{ .cmd = "a", .args = &.{"bc"}, .cwd = "/repo" });
    defer allocator.free(second);
    try std.testing.expect(!std.mem.eql(u8, first, second));
}
