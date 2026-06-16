const std = @import("std");

pub fn render(allocator: std.mem.Allocator, aws_profile_env: ?[]const u8, home: ?[]const u8) !?[]u8 {
    const profile = (try awsProfileAlloc(allocator, aws_profile_env, home)) orelse return null;
    defer allocator.free(profile);
    return try std.fmt.allocPrint(allocator, "aws:{s}", .{profile});
}

pub fn awsProfileAlloc(allocator: std.mem.Allocator, aws_profile_env: ?[]const u8, home: ?[]const u8) !?[]u8 {
    if (aws_profile_env) |value| {
        const trimmed = std.mem.trim(u8, value, " \t\r\n");
        if (trimmed.len != 0) return @as(?[]u8, try allocator.dupe(u8, trimmed));
    }

    const home_path = home orelse return null;
    const config_path = try std.fmt.allocPrint(allocator, "{s}/.aws/config", .{home_path});
    defer allocator.free(config_path);
    const source = std.fs.cwd().readFileAlloc(allocator, config_path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAwsConfigProfileAlloc(allocator, source);
}

pub fn parseAwsConfigProfileAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var first_profile: ?[]const u8 = null;
    var has_default = false;

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len < 3 or line[0] == '#' or line[0] == ';') continue;
        if (line[0] != '[' or line[line.len - 1] != ']') continue;

        const section = std.mem.trim(u8, line[1 .. line.len - 1], " \t");
        if (std.mem.eql(u8, section, "default")) {
            has_default = true;
        } else if (std.mem.startsWith(u8, section, "profile ")) {
            const profile = std.mem.trim(u8, section["profile ".len..], " \t");
            if (profile.len != 0 and first_profile == null) first_profile = profile;
        }
    }

    if (has_default) return @as(?[]u8, try allocator.dupe(u8, "default"));
    if (first_profile) |profile| return @as(?[]u8, try allocator.dupe(u8, profile));
    return null;
}

test "aws profile env wins" {
    const profile = (try awsProfileAlloc(std.testing.allocator, " prod ", null)).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("prod", profile);
}

test "parses default aws config profile" {
    const profile = (try parseAwsConfigProfileAlloc(std.testing.allocator,
        \\[default]
        \\region = us-east-1
        \\
        \\[profile staging]
        \\region = us-west-2
        \\
    )).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("default", profile);
}

test "parses first named aws config profile" {
    const profile = (try parseAwsConfigProfileAlloc(std.testing.allocator,
        \\[profile staging]
        \\region = us-west-2
        \\
        \\[profile prod]
        \\region = us-east-1
        \\
    )).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("staging", profile);
}

test "renders aws cloud context" {
    const rendered = (try render(std.testing.allocator, "prod", null)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("aws:prod", rendered);
}
