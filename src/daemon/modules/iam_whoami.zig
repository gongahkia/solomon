const std = @import("std");

pub const module_id = "iam_whoami";

const AwsStsIdentityJson = struct {
    UserId: []const u8 = "",
    Account: []const u8 = "",
    Arn: []const u8 = "",
};

const GcloudAuthJson = struct {
    account: []const u8 = "",
    status: []const u8 = "",
};

pub fn awsStsCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8, profile: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    const profile_name = sanitizeProfile(profile orelse "default");
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/aws-sts-{s}.json", .{ home_path, profile_name }));
}

pub fn readAwsStsIdentityAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAwsStsIdentityAlloc(allocator, source);
}

pub fn parseAwsStsIdentityAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AwsStsIdentityJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const arn = std.mem.trim(u8, parsed.value.Arn, " \t\r\n");
    if (arn.len != 0) return @as(?[]u8, try allocator.dupe(u8, arn));
    const account = std.mem.trim(u8, parsed.value.Account, " \t\r\n");
    if (account.len != 0) return @as(?[]u8, try allocator.dupe(u8, account));
    const user_id = std.mem.trim(u8, parsed.value.UserId, " \t\r\n");
    if (user_id.len != 0) return @as(?[]u8, try allocator.dupe(u8, user_id));
    return null;
}

pub fn gcloudAuthCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/gcloud-auth-list.json", .{home_path}));
}

pub fn readGcloudAuthAccountAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseGcloudAuthAccountAlloc(allocator, source);
}

pub fn parseGcloudAuthAccountAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice([]GcloudAuthJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    var fallback: ?[]const u8 = null;
    for (parsed.value) |entry| {
        const account = std.mem.trim(u8, entry.account, " \t\r\n");
        if (account.len == 0) continue;
        if (fallback == null) fallback = account;
        if (std.ascii.eqlIgnoreCase(std.mem.trim(u8, entry.status, " \t\r\n"), "ACTIVE")) {
            return @as(?[]u8, try allocator.dupe(u8, account));
        }
    }
    if (fallback) |account| return @as(?[]u8, try allocator.dupe(u8, account));
    return null;
}

fn sanitizeProfile(profile: []const u8) []const u8 {
    if (safeProfile(profile)) return profile;
    return "default";
}

fn safeProfile(profile: []const u8) bool {
    if (profile.len == 0) return false;
    for (profile) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_' or byte == '-' or byte == '.')) return false;
    }
    return true;
}

test "parses aws sts identity arn" {
    const identity = (try parseAwsStsIdentityAlloc(std.testing.allocator,
        \\{
        \\  "UserId": "AIDAEXAMPLE",
        \\  "Account": "123456789012",
        \\  "Arn": "arn:aws:iam::123456789012:user/alice"
        \\}
    )).?;
    defer std.testing.allocator.free(identity);
    try std.testing.expectEqualStrings("arn:aws:iam::123456789012:user/alice", identity);
}

test "parses aws sts identity account fallback" {
    const identity = (try parseAwsStsIdentityAlloc(std.testing.allocator,
        \\{
        \\  "Account": "123456789012"
        \\}
    )).?;
    defer std.testing.allocator.free(identity);
    try std.testing.expectEqualStrings("123456789012", identity);
}

test "builds aws sts cache path" {
    const path = (try awsStsCachePathAlloc(std.testing.allocator, "/home/me", "prod")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/aws-sts-prod.json", path);
}

test "unsafe profile falls back in path" {
    const path = (try awsStsCachePathAlloc(std.testing.allocator, "/home/me", "../prod")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/aws-sts-default.json", path);
}

test "parses gcloud active account" {
    const account = (try parseGcloudAuthAccountAlloc(std.testing.allocator,
        \\[
        \\  {"account": "old@example.com", "status": ""},
        \\  {"account": "active@example.com", "status": "ACTIVE"}
        \\]
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("active@example.com", account);
}

test "parses gcloud account fallback" {
    const account = (try parseGcloudAuthAccountAlloc(std.testing.allocator,
        \\[
        \\  {"account": "first@example.com"}
        \\]
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("first@example.com", account);
}

test "builds gcloud auth cache path" {
    const path = (try gcloudAuthCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/gcloud-auth-list.json", path);
}
