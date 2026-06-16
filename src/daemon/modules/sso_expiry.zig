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

pub const Options = struct {
    warning_minutes: u32 = 30,
};

const Candidate = struct {
    provider: []const u8,
    remaining_seconds: i64,
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

pub fn opSigninStatusCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/op-signin-status.json", .{home_path}));
}

pub fn readOpSigninStatusExpiryAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 64 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseOpSigninStatusExpiryAlloc(allocator, source);
}

pub fn parseOpSigninStatusExpiryAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    const trimmed = std.mem.trim(u8, source, " \t\r\n");
    if (trimmed.len == 0) return null;
    var parsed = std.json.parseFromSlice(std.json.Value, allocator, trimmed, .{}) catch return null;
    defer parsed.deinit();
    return opSigninStatusExpiryFromValueAlloc(allocator, parsed.value);
}

fn opSigninStatusExpiryFromValueAlloc(allocator: std.mem.Allocator, value: std.json.Value) !?[]u8 {
    switch (value) {
        .object => |object| {
            const fields = [_][]const u8{ "expires_at", "expiresAt", "expiry", "expires", "valid_until", "validUntil", "session_expires_at", "sessionExpiresAt", "expires_in", "expiresIn", "ttl" };
            for (fields) |field| {
                if (object.get(field)) |entry| {
                    if (try jsonScalarTextAlloc(allocator, entry)) |text| return text;
                }
            }
            if (object.get("session")) |session| {
                if (try opSigninStatusExpiryFromValueAlloc(allocator, session)) |text| return text;
            }
            if (object.get("auth")) |auth| {
                if (try opSigninStatusExpiryFromValueAlloc(allocator, auth)) |text| return text;
            }
            if (object.get("data")) |data| {
                if (try opSigninStatusExpiryFromValueAlloc(allocator, data)) |text| return text;
            }
            return null;
        },
        else => return null,
    }
}

pub fn render(allocator: std.mem.Allocator, home: ?[]const u8, now_timestamp: i64, options: Options) !?[]u8 {
    const threshold_seconds = @as(i64, @intCast(options.warning_minutes)) * std.time.s_per_min;
    var best: ?Candidate = null;

    const aws = try readAwsSsoSoonestExpiryAlloc(allocator, home);
    defer if (aws) |value| allocator.free(value);
    considerExpiry(&best, "aws", aws, now_timestamp, threshold_seconds);

    const gcloud_path = try gcloudAuthCachePathAlloc(allocator, home);
    defer if (gcloud_path) |value| allocator.free(value);
    const gcloud = if (gcloud_path) |path| try readGcloudAuthExpiryAlloc(allocator, path) else null;
    defer if (gcloud) |value| allocator.free(value);
    considerExpiry(&best, "gcp", gcloud, now_timestamp, threshold_seconds);

    const azure_path = try azureAccessTokensPathAlloc(allocator, home);
    defer if (azure_path) |value| allocator.free(value);
    const azure = if (azure_path) |path| try readAzureAccessTokenExpiryAlloc(allocator, path) else null;
    defer if (azure) |value| allocator.free(value);
    considerExpiry(&best, "az", azure, now_timestamp, threshold_seconds);

    const vault_path = try vaultTokenPathAlloc(allocator, home);
    defer if (vault_path) |value| allocator.free(value);
    const vault = if (vault_path) |path| try readVaultTokenLeaseInfoAlloc(allocator, path) else null;
    defer if (vault) |value| allocator.free(value);
    considerExpiry(&best, "vault", vault, now_timestamp, threshold_seconds);

    const op_path = try opSigninStatusCachePathAlloc(allocator, home);
    defer if (op_path) |value| allocator.free(value);
    const op = if (op_path) |path| try readOpSigninStatusExpiryAlloc(allocator, path) else null;
    defer if (op) |value| allocator.free(value);
    considerExpiry(&best, "op", op, now_timestamp, threshold_seconds);

    const warning = best orelse return null;
    const minutes = remainingMinutes(warning.remaining_seconds);
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "sso[{s}:{d}m]", .{ warning.provider, minutes }));
}

fn considerExpiry(best: *?Candidate, provider: []const u8, value: ?[]const u8, now_timestamp: i64, threshold_seconds: i64) void {
    const expiry = value orelse return;
    const remaining = remainingSeconds(expiry, now_timestamp) orelse return;
    if (remaining >= threshold_seconds) return;
    if (best.* == null or remaining < best.*.?.remaining_seconds) {
        best.* = .{ .provider = provider, .remaining_seconds = remaining };
    }
}

fn remainingSeconds(value: []const u8, now_timestamp: i64) ?i64 {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (trimmed.len == 0) return null;
    if (std.fmt.parseInt(i64, trimmed, 10)) |number| {
        if (number > 1_000_000_000) return number - now_timestamp;
        return number;
    } else |_| {}
    const absolute = parseDateTimeSeconds(trimmed) orelse return null;
    return absolute - now_timestamp;
}

fn remainingMinutes(seconds: i64) i64 {
    if (seconds <= 0) return 0;
    return @divTrunc(seconds + 59, 60);
}

fn parseDateTimeSeconds(value: []const u8) ?i64 {
    if (value.len < 19) return null;
    if (value[4] != '-' or value[7] != '-' or (value[10] != 'T' and value[10] != ' ') or value[13] != ':' or value[16] != ':') return null;
    const year = std.fmt.parseInt(u16, value[0..4], 10) catch return null;
    const month = std.fmt.parseInt(u8, value[5..7], 10) catch return null;
    const day = std.fmt.parseInt(u8, value[8..10], 10) catch return null;
    const hour = std.fmt.parseInt(u8, value[11..13], 10) catch return null;
    const minute = std.fmt.parseInt(u8, value[14..16], 10) catch return null;
    const second = std.fmt.parseInt(u8, value[17..19], 10) catch return null;
    const base = epochSeconds(year, month, day, hour, minute, second) orelse return null;

    var index: usize = 19;
    if (index < value.len and value[index] == '.') {
        index += 1;
        while (index < value.len and std.ascii.isDigit(value[index])) : (index += 1) {}
    }
    const suffix = std.mem.trim(u8, value[index..], " \t\r\n");
    if (suffix.len == 0 or std.mem.eql(u8, suffix, "Z")) return base;
    if (suffix.len == 6 and (suffix[0] == '+' or suffix[0] == '-') and suffix[3] == ':') {
        const offset_hours = std.fmt.parseInt(i64, suffix[1..3], 10) catch return null;
        const offset_minutes = std.fmt.parseInt(i64, suffix[4..6], 10) catch return null;
        if (offset_hours > 23 or offset_minutes > 59) return null;
        const offset = offset_hours * std.time.s_per_hour + offset_minutes * std.time.s_per_min;
        return if (suffix[0] == '+') base - offset else base + offset;
    }
    return null;
}

fn epochSeconds(year: u16, month: u8, day: u8, hour: u8, minute: u8, second: u8) ?i64 {
    if (year < 1970 or month < 1 or month > 12 or hour > 23 or minute > 59 or second > 59) return null;
    const month_days = daysInMonth(year, month);
    if (day < 1 or day > month_days) return null;

    var days: i64 = 0;
    var cursor_year: u16 = 1970;
    while (cursor_year < year) : (cursor_year += 1) {
        days += if (isLeapYear(cursor_year)) 366 else 365;
    }
    var cursor_month: u8 = 1;
    while (cursor_month < month) : (cursor_month += 1) {
        days += @as(i64, @intCast(daysInMonth(year, cursor_month)));
    }
    days += @as(i64, @intCast(day - 1));
    return days * std.time.s_per_day + @as(i64, @intCast(hour)) * std.time.s_per_hour + @as(i64, @intCast(minute)) * std.time.s_per_min + @as(i64, @intCast(second));
}

fn isLeapYear(year: u16) bool {
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0;
}

fn daysInMonth(year: u16, month: u8) u8 {
    return switch (month) {
        1, 3, 5, 7, 8, 10, 12 => 31,
        4, 6, 9, 11 => 30,
        2 => if (isLeapYear(year)) 29 else 28,
        else => 0,
    };
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

test "parses op signin status expiry" {
    const expiry = (try parseOpSigninStatusExpiryAlloc(std.testing.allocator,
        \\{
        \\  "account": "acme",
        \\  "status": "signed_in",
        \\  "expires_at": "2026-06-16T12:00:00Z"
        \\}
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("2026-06-16T12:00:00Z", expiry);
}

test "parses nested op signin ttl" {
    const expiry = (try parseOpSigninStatusExpiryAlloc(std.testing.allocator,
        \\{
        \\  "session": {"expires_in": 1800}
        \\}
    )).?;
    defer std.testing.allocator.free(expiry);
    try std.testing.expectEqualStrings("1800", expiry);
}

test "builds op signin status cache path" {
    const path = (try opSigninStatusCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/op-signin-status.json", path);
}

test "parses absolute expiry seconds" {
    try std.testing.expectEqual(@as(i64, 1200), remainingSeconds("1970-01-01T00:20:00Z", 0).?);
    try std.testing.expectEqual(@as(i64, 1200), remainingSeconds("1970-01-01 00:20:00.000000", 0).?);
    try std.testing.expectEqual(@as(i64, 1200), remainingSeconds("1970-01-01T01:20:00+01:00", 0).?);
}

test "renders soonest sso warning" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sso-render-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const cache_dir = try std.fmt.allocPrint(allocator, "{s}/.cache/shisa", .{dir_path});
    defer allocator.free(cache_dir);
    try std.fs.cwd().makePath(cache_dir);
    const op_path = try std.fmt.allocPrint(allocator, "{s}/op-signin-status.json", .{cache_dir});
    defer allocator.free(op_path);
    {
        var file = try std.fs.createFileAbsolute(op_path, .{});
        defer file.close();
        try file.writeAll("{\"session\":{\"expires_in\":1200}}");
    }

    const warning = (try render(allocator, dir_path, 0, .{ .warning_minutes = 30 })).?;
    defer allocator.free(warning);
    try std.testing.expectEqualStrings("sso[op:20m]", warning);
    const no_warning = try render(allocator, dir_path, 0, .{ .warning_minutes = 10 });
    try std.testing.expect(no_warning == null);
}
