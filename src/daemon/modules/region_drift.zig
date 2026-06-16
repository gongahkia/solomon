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

pub fn gcpConfigPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    const config_dir = try std.fmt.allocPrint(allocator, "{s}/.config/gcloud", .{home_path});
    defer allocator.free(config_dir);
    const active_path = try std.fmt.allocPrint(allocator, "{s}/active_config", .{config_dir});
    defer allocator.free(active_path);

    const active_source = std.fs.cwd().readFileAlloc(allocator, active_path, 4096) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
    defer if (active_source) |value| allocator.free(value);
    const active_name = if (active_source) |value| std.mem.trim(u8, value, " \t\r\n") else "default";
    const name = if (active_name.len == 0) "default" else active_name;
    if (!safeGcloudConfigName(name)) return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/configurations/config_{s}", .{ config_dir, name }));
}

pub fn readGcpConfigRegionAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const path = (try gcpConfigPathAlloc(allocator, home)) orelse return null;
    defer allocator.free(path);
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseGcpConfigRegionAlloc(allocator, source);
}

pub fn parseGcpConfigRegionAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var in_compute = false;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#' or line[0] == ';') continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            const section = std.mem.trim(u8, line[1 .. line.len - 1], " \t");
            in_compute = std.mem.eql(u8, section, "compute");
            continue;
        }
        if (!in_compute) continue;
        const value = iniValue(line, "region") orelse continue;
        if (value.len != 0) return @as(?[]u8, try allocator.dupe(u8, value));
    }
    return null;
}

pub fn gcpRegionDriftAlloc(allocator: std.mem.Allocator, home: ?[]const u8, cloudsdk_compute_region: ?[]const u8) !?[]u8 {
    const env_region = trimEnv(cloudsdk_compute_region) orelse return null;
    const config_region = (try readGcpConfigRegionAlloc(allocator, home)) orelse return null;
    defer allocator.free(config_region);
    if (std.mem.eql(u8, env_region, config_region)) return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "gcp:{s}!={s}", .{ env_region, config_region }));
}

pub fn azureConfigPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.azure/config", .{home_path}));
}

pub fn azureEnvRegion(azure_location: ?[]const u8, arm_location: ?[]const u8, azure_default_location: ?[]const u8) ?[]const u8 {
    if (trimEnv(azure_location)) |value| return value;
    if (trimEnv(arm_location)) |value| return value;
    return trimEnv(azure_default_location);
}

pub fn readAzureDefaultLocationAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const path = (try azureConfigPathAlloc(allocator, home)) orelse return null;
    defer allocator.free(path);
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAzureDefaultLocationAlloc(allocator, source);
}

pub fn parseAzureDefaultLocationAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var in_defaults = false;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#' or line[0] == ';') continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            const section = std.mem.trim(u8, line[1 .. line.len - 1], " \t");
            in_defaults = std.mem.eql(u8, section, "defaults");
            continue;
        }
        if (!in_defaults) continue;
        const value = iniValue(line, "location") orelse iniValue(line, "region") orelse continue;
        if (value.len != 0) return @as(?[]u8, try allocator.dupe(u8, value));
    }
    return null;
}

pub fn azureRegionDriftAlloc(allocator: std.mem.Allocator, home: ?[]const u8, azure_location: ?[]const u8, arm_location: ?[]const u8, azure_default_location: ?[]const u8) !?[]u8 {
    const env_region = azureEnvRegion(azure_location, arm_location, azure_default_location) orelse return null;
    const config_region = (try readAzureDefaultLocationAlloc(allocator, home)) orelse return null;
    defer allocator.free(config_region);
    if (std.mem.eql(u8, env_region, config_region)) return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "az:{s}!={s}", .{ env_region, config_region }));
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

fn trimEnv(value: ?[]const u8) ?[]const u8 {
    if (value) |raw| {
        const trimmed = std.mem.trim(u8, raw, " \t\r\n");
        if (trimmed.len != 0) return trimmed;
    }
    return null;
}

fn safeGcloudConfigName(name: []const u8) bool {
    for (name) |byte| {
        if (byte == '/' or byte == '\\' or byte == 0) return false;
    }
    return true;
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

test "parses gcp compute region" {
    const region = (try parseGcpConfigRegionAlloc(std.testing.allocator,
        \\[core]
        \\project = demo
        \\
        \\[compute]
        \\region = asia-southeast1
        \\
    )).?;
    defer std.testing.allocator.free(region);
    try std.testing.expectEqualStrings("asia-southeast1", region);
}

test "detects gcp region drift" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-gcp-region-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const gcloud_dir = try std.fmt.allocPrint(allocator, "{s}/.config/gcloud/configurations", .{dir_path});
    defer allocator.free(gcloud_dir);
    try std.fs.cwd().makePath(gcloud_dir);

    const config_path = try std.fmt.allocPrint(allocator, "{s}/config_default", .{gcloud_dir});
    defer allocator.free(config_path);
    {
        var file = try std.fs.createFileAbsolute(config_path, .{});
        defer file.close();
        try file.writeAll("[compute]\nregion = us-central1\n");
    }

    const drift = (try gcpRegionDriftAlloc(allocator, dir_path, "europe-west1")).?;
    defer allocator.free(drift);
    try std.testing.expectEqualStrings("gcp:europe-west1!=us-central1", drift);
    try std.testing.expect(try gcpRegionDriftAlloc(allocator, dir_path, "us-central1") == null);
}

test "parses azure default location" {
    const location = (try parseAzureDefaultLocationAlloc(std.testing.allocator,
        \\[cloud]
        \\name = AzureCloud
        \\
        \\[defaults]
        \\location = eastus
        \\
    )).?;
    defer std.testing.allocator.free(location);
    try std.testing.expectEqualStrings("eastus", location);
}

test "detects azure region drift" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-azure-region-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const azure_dir = try std.fmt.allocPrint(allocator, "{s}/.azure", .{dir_path});
    defer allocator.free(azure_dir);
    try std.fs.cwd().makePath(azure_dir);

    const config_path = try std.fmt.allocPrint(allocator, "{s}/config", .{azure_dir});
    defer allocator.free(config_path);
    {
        var file = try std.fs.createFileAbsolute(config_path, .{});
        defer file.close();
        try file.writeAll("[defaults]\nlocation = eastus\n");
    }

    const drift = (try azureRegionDriftAlloc(allocator, dir_path, "westus", null, null)).?;
    defer allocator.free(drift);
    try std.testing.expectEqualStrings("az:westus!=eastus", drift);
    try std.testing.expect(try azureRegionDriftAlloc(allocator, dir_path, "eastus", null, null) == null);
}
