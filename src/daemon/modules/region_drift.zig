const std = @import("std");

pub const module_id = "region_drift";

pub fn awsConfigPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.aws/config", .{home_path}));
}

pub fn awsEnvRegion(aws_region: ?[]const u8, aws_default_region: ?[]const u8) ?[]const u8 {
    if (aws_region) |value| {
        const trimmed = std.mem.trim(u8, value, " \t\r\n");
        if (trimmed.len != 0) return trimmed;
    }
    if (aws_default_region) |value| {
        const trimmed = std.mem.trim(u8, value, " \t\r\n");
        if (trimmed.len != 0) return trimmed;
    }
    return null;
}

pub fn readAwsProfileRegionAlloc(allocator: std.mem.Allocator, home: ?[]const u8, profile: ?[]const u8) !?[]u8 {
    const path = (try awsConfigPathAlloc(allocator, home)) orelse return null;
    defer allocator.free(path);
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAwsConfigRegionAlloc(allocator, source, profile);
}

pub fn parseAwsConfigRegionAlloc(allocator: std.mem.Allocator, source: []const u8, profile: ?[]const u8) !?[]u8 {
    const selected_profile = std.mem.trim(u8, profile orelse "default", " \t\r\n");
    const normalized_profile = if (selected_profile.len == 0) "default" else selected_profile;
    var in_profile = false;

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#' or line[0] == ';') continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            const section = std.mem.trim(u8, line[1 .. line.len - 1], " \t");
            in_profile = awsSectionMatchesProfile(section, normalized_profile);
            continue;
        }
        if (!in_profile) continue;
        const value = iniValue(line, "region") orelse continue;
        if (value.len != 0) return @as(?[]u8, try allocator.dupe(u8, value));
    }
    return null;
}

pub fn awsRegionDriftAlloc(allocator: std.mem.Allocator, home: ?[]const u8, profile: ?[]const u8, aws_region: ?[]const u8, aws_default_region: ?[]const u8) !?[]u8 {
    const env_region = awsEnvRegion(aws_region, aws_default_region) orelse return null;
    const config_region = (try readAwsProfileRegionAlloc(allocator, home, profile)) orelse return null;
    defer allocator.free(config_region);
    if (std.mem.eql(u8, env_region, config_region)) return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "aws:{s}!={s}", .{ env_region, config_region }));
}

fn awsSectionMatchesProfile(section: []const u8, profile: []const u8) bool {
    if (std.mem.eql(u8, profile, "default")) return std.mem.eql(u8, section, "default");
    if (std.mem.eql(u8, section, profile)) return true;
    if (!std.mem.startsWith(u8, section, "profile ")) return false;
    return std.mem.eql(u8, std.mem.trim(u8, section["profile ".len..], " \t"), profile);
}

fn iniValue(line: []const u8, key: []const u8) ?[]const u8 {
    const eq_index = std.mem.indexOfScalar(u8, line, '=') orelse return null;
    const parsed_key = std.mem.trim(u8, line[0..eq_index], " \t");
    if (!std.mem.eql(u8, parsed_key, key)) return null;
    return std.mem.trim(u8, line[eq_index + 1 ..], " \t\r\n");
}

test "aws env region prefers AWS_REGION" {
    try std.testing.expectEqualStrings("us-west-2", awsEnvRegion(" us-west-2 ", "us-east-1").?);
    try std.testing.expectEqualStrings("us-east-1", awsEnvRegion(null, " us-east-1 ").?);
}

test "parses aws profile region" {
    const region = (try parseAwsConfigRegionAlloc(std.testing.allocator,
        \\[default]
        \\region = us-east-1
        \\
        \\[profile prod]
        \\region = us-west-2
        \\
    , "prod")).?;
    defer std.testing.allocator.free(region);
    try std.testing.expectEqualStrings("us-west-2", region);
}

test "detects aws region drift" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-region-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const aws_dir = try std.fmt.allocPrint(allocator, "{s}/.aws", .{dir_path});
    defer allocator.free(aws_dir);
    try std.fs.cwd().makePath(aws_dir);

    const config_path = try std.fmt.allocPrint(allocator, "{s}/config", .{aws_dir});
    defer allocator.free(config_path);
    {
        var file = try std.fs.createFileAbsolute(config_path, .{});
        defer file.close();
        try file.writeAll("[profile prod]\nregion = us-east-1\n");
    }

    const drift = (try awsRegionDriftAlloc(allocator, dir_path, "prod", "us-west-2", null)).?;
    defer allocator.free(drift);
    try std.testing.expectEqualStrings("aws:us-west-2!=us-east-1", drift);
    try std.testing.expect(try awsRegionDriftAlloc(allocator, dir_path, "prod", "us-east-1", null) == null);
}
