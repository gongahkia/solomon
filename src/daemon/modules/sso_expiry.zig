const std = @import("std");

pub const module_id = "sso_expiry";

const AwsSsoCacheJson = struct {
    expiresAt: []const u8 = "",
};

const GcloudAuthJson = struct {
    account: []const u8 = "",
    status: []const u8 = "",
    token_expiry: []const u8 = "",
    expiresAt: []const u8 = "",
    expiry: []const u8 = "",
};

const AzureAccessTokenJson = struct {
    expiresOn: []const u8 = "",
    expires_on: []const u8 = "",
    expiresAt: []const u8 = "",
    expires_at: []const u8 = "",
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

pub fn gcloudAuthCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/gcloud-auth-list.json", .{home_path}));
}

pub fn readGcloudAuthExpiryAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseGcloudAuthExpiryAlloc(allocator, source);
}

pub fn parseGcloudAuthExpiryAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice([]GcloudAuthJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    var fallback: ?[]const u8 = null;
    for (parsed.value) |entry| {
        const expiry = gcloudExpiryField(entry) orelse continue;
        if (fallback == null) fallback = expiry;
        if (std.ascii.eqlIgnoreCase(std.mem.trim(u8, entry.status, " \t\r\n"), "ACTIVE")) {
            return @as(?[]u8, try allocator.dupe(u8, expiry));
        }
    }
    if (fallback) |expiry| return @as(?[]u8, try allocator.dupe(u8, expiry));
    return null;
}

fn gcloudExpiryField(entry: GcloudAuthJson) ?[]const u8 {
    const token_expiry = std.mem.trim(u8, entry.token_expiry, " \t\r\n");
    if (token_expiry.len != 0) return token_expiry;
    const expires_at = std.mem.trim(u8, entry.expiresAt, " \t\r\n");
    if (expires_at.len != 0) return expires_at;
    const expiry = std.mem.trim(u8, entry.expiry, " \t\r\n");
    if (expiry.len != 0) return expiry;
    return null;
}

pub fn azureAccessTokensPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.azure/accessTokens.json", .{home_path}));
}

pub fn readAzureAccessTokenExpiryAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAzureAccessTokenExpiryAlloc(allocator, source);
}

pub fn parseAzureAccessTokenExpiryAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice([]AzureAccessTokenJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    var soonest: ?[]const u8 = null;
    for (parsed.value) |entry| {
        const expiry = azureExpiryField(entry) orelse continue;
        if (soonest == null or std.mem.lessThan(u8, expiry, soonest.?)) soonest = expiry;
    }
    if (soonest) |expiry| return @as(?[]u8, try allocator.dupe(u8, expiry));
    return null;
}

fn azureExpiryField(entry: AzureAccessTokenJson) ?[]const u8 {
    const expires_on = std.mem.trim(u8, entry.expiresOn, " \t\r\n");
    if (expires_on.len != 0) return expires_on;
    const expires_on_alt = std.mem.trim(u8, entry.expires_on, " \t\r\n");
    if (expires_on_alt.len != 0) return expires_on_alt;
    const expires_at = std.mem.trim(u8, entry.expiresAt, " \t\r\n");
    if (expires_at.len != 0) return expires_at;
    const expires_at_alt = std.mem.trim(u8, entry.expires_at, " \t\r\n");
    if (expires_at_alt.len != 0) return expires_at_alt;
    return null;
}

pub fn vaultTokenPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.vault-token", .{home_path}));
}

pub fn readVaultTokenLeaseInfoAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 64 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseVaultTokenLeaseInfoAlloc(allocator, source);
}

pub fn parseVaultTokenLeaseInfoAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    const trimmed = std.mem.trim(u8, source, " \t\r\n");
    if (trimmed.len == 0) return null;
    var parsed = std.json.parseFromSlice(std.json.Value, allocator, trimmed, .{}) catch return null;
    defer parsed.deinit();
    return vaultLeaseInfoFromValueAlloc(allocator, parsed.value);
}

fn vaultLeaseInfoFromValueAlloc(allocator: std.mem.Allocator, value: std.json.Value) !?[]u8 {
    switch (value) {
        .object => |object| {
            const fields = [_][]const u8{ "expire_time", "expireTime", "expires_at", "expiresAt", "ttl", "lease_duration", "token_duration" };
            for (fields) |field| {
                if (object.get(field)) |entry| {
                    if (try jsonScalarTextAlloc(allocator, entry)) |text| return text;
                }
            }
            if (object.get("auth")) |auth| {
                if (try vaultLeaseInfoFromValueAlloc(allocator, auth)) |text| return text;
            }
            if (object.get("data")) |data| {
                if (try vaultLeaseInfoFromValueAlloc(allocator, data)) |text| return text;
            }
            return null;
        },
        else => return null,
    }
}

fn jsonScalarTextAlloc(allocator: std.mem.Allocator, value: std.json.Value) !?[]u8 {
    switch (value) {
        .string => |text| {
            const trimmed = std.mem.trim(u8, text, " \t\r\n");
            if (trimmed.len == 0) return null;
            return @as(?[]u8, try allocator.dupe(u8, trimmed));
        },
        .integer => |number| return @as(?[]u8, try std.fmt.allocPrint(allocator, "{d}", .{number})),
        .number_string => |text| {
            const trimmed = std.mem.trim(u8, text, " \t\r\n");
            if (trimmed.len == 0) return null;
            return @as(?[]u8, try allocator.dupe(u8, trimmed));
        },
        else => return null,
    }
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

test "parses gcloud active expiry" {
    const expiry = (try parseGcloudAuthExpiryAlloc(std.testing.allocator,
        \\[
        \\  {"account": "old@example.com", "token_expiry": "2026-06-16T12:00:00Z"},
        \\  {"account": "active@example.com", "status": "ACTIVE", "token_expiry": "2026-06-16T10:00:00Z"}
        \\]
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T10:00:00Z", expiry);
}

test "builds gcloud auth cache path for expiry" {
    const path = (try gcloudAuthCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/gcloud-auth-list.json", path);
}

test "parses azure access token soonest expiry" {
    const expiry = (try parseAzureAccessTokenExpiryAlloc(std.testing.allocator,
        \\[
        \\  {"resource": "https://management.azure.com/", "expiresOn": "2026-06-16 12:00:00.000000"},
        \\  {"resource": "https://graph.microsoft.com/", "expiresOn": "2026-06-16 10:00:00.000000"}
        \\]
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16 10:00:00.000000", expiry);
}

test "parses azure access token fallback expiry fields" {
    const expiry = (try parseAzureAccessTokenExpiryAlloc(std.testing.allocator,
        \\[
        \\  {"expires_at": "2026-06-16T12:00:00Z"},
        \\  {"expires_on": "2026-06-16T10:00:00Z"}
        \\]
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T10:00:00Z", expiry);
}

test "builds azure access tokens path" {
    const path = (try azureAccessTokensPathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.azure/accessTokens.json", path);
}

test "parses vault token expire time" {
    const expiry = (try parseVaultTokenLeaseInfoAlloc(std.testing.allocator,
        \\{
        \\  "expire_time": "2026-06-16T12:00:00Z"
        \\}
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T12:00:00Z", expiry);
}

test "parses nested vault lease duration" {
    const expiry = (try parseVaultTokenLeaseInfoAlloc(std.testing.allocator,
        \\{
        \\  "auth": {"client_token": "hvs.redacted", "lease_duration": 3600}
        \\}
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("3600", expiry);
}

test "ignores raw vault token without lease metadata" {
    const expiry = try parseVaultTokenLeaseInfoAlloc(std.testing.allocator, "hvs.redacted\n");
    try std.testing.expect(expiry == null);
}

test "builds vault token path" {
    const path = (try vaultTokenPathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.vault-token", path);
}
