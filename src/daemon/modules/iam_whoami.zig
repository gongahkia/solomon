const std = @import("std");

pub const module_id = "iam_whoami";

const AwsStsIdentityJson = struct {
    UserId: []const u8 = "",
    Account: []const u8 = "",
    Arn: []const u8 = "",
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
