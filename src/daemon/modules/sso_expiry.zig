const std = @import("std");

pub const module_id = "sso_expiry";

const AwsSsoCacheJson = struct {
    expiresAt: []const u8 = "",
};

pub fn awsSsoCacheDirAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.aws/sso/cache", .{home_path}));
}

pub fn readAwsSsoSoonestExpiryAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const dir_path = (try awsSsoCacheDirAlloc(allocator, home)) orelse return null;
    defer allocator.free(dir_path);
    var dir = std.fs.openDirAbsolute(dir_path, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer dir.close();

    var soonest: ?[]u8 = null;
    errdefer if (soonest) |value| allocator.free(value);
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".json")) continue;
        const source = dir.readFileAlloc(allocator, entry.name, 256 * 1024) catch continue;
        defer allocator.free(source);
        const expiry = try parseAwsSsoExpiryAlloc(allocator, source) orelse continue;
        defer allocator.free(expiry);
        if (soonest == null or std.mem.lessThan(u8, expiry, soonest.?)) {
            if (soonest) |value| allocator.free(value);
            soonest = try allocator.dupe(u8, expiry);
        }
    }
    return soonest;
}

pub fn parseAwsSsoExpiryAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AwsSsoCacheJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const expiry = std.mem.trim(u8, parsed.value.expiresAt, " \t\r\n");
    if (expiry.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, expiry));
}

test "parses aws sso expiry" {
    const expiry = (try parseAwsSsoExpiryAlloc(std.testing.allocator,
        \\{
        \\  "startUrl": "https://example.awsapps.com/start",
        \\  "expiresAt": "2026-06-16T12:00:00Z"
        \\}
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T12:00:00Z", expiry);
}

test "reads soonest aws sso expiry" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sso-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const cache_dir = try std.fmt.allocPrint(allocator, "{s}/.aws/sso/cache", .{dir_path});
    defer allocator.free(cache_dir);
    try std.fs.cwd().makePath(cache_dir);

    const first_path = try std.fmt.allocPrint(allocator, "{s}/a.json", .{cache_dir});
    defer allocator.free(first_path);
    const second_path = try std.fmt.allocPrint(allocator, "{s}/b.json", .{cache_dir});
    defer allocator.free(second_path);
    {
        var file = try std.fs.createFileAbsolute(first_path, .{});
        defer file.close();
        try file.writeAll("{\"expiresAt\":\"2026-06-16T12:00:00Z\"}");
    }
    {
        var file = try std.fs.createFileAbsolute(second_path, .{});
        defer file.close();
        try file.writeAll("{\"expiresAt\":\"2026-06-16T10:00:00Z\"}");
    }

    const expiry = (try readAwsSsoSoonestExpiryAlloc(allocator, dir_path)).?;
    defer allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T10:00:00Z", expiry);
}

test "builds aws sso cache dir" {
    const path = (try awsSsoCacheDirAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.aws/sso/cache", path);
}
