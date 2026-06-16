const std = @import("std");

pub const module_id = "cloud_ctx";

pub const WatchPath = struct {
    path: []const u8,
    recursive: bool = false,
};

pub const Scope = struct {
    module_id: []const u8,
    cwd: []const u8,
    paths: []const WatchPath,
    debounce_ms: u64 = 50,
};

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    valid: bool = false,
    gcp_project: ?[]u8 = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn invalidateGcp(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearLocked(allocator);
    }

    pub fn gcpProjectAlloc(self: *Cache, allocator: std.mem.Allocator) !?[]u8 {
        self.mutex.lock();
        if (self.valid) {
            const project = if (self.gcp_project) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return project;
        }
        self.mutex.unlock();

        const project = try readGcpProjectAlloc(allocator);
        errdefer if (project) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearLocked(allocator);
        self.valid = true;
        self.gcp_project = if (project) |value| try allocator.dupe(u8, value) else null;
        return project;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearLocked(allocator);
    }

    fn clearLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.gcp_project) |value| allocator.free(value);
        self.gcp_project = null;
        self.valid = false;
    }
};

pub const WatchScope = struct {
    cwd: []u8,
    gcloud_config_path: []u8,
    paths: [1]WatchPath,

    pub fn scope(self: *const WatchScope) Scope {
        return .{
            .module_id = module_id,
            .cwd = self.cwd,
            .paths = self.paths[0..],
            .debounce_ms = 50,
        };
    }

    pub fn deinit(self: *WatchScope, allocator: std.mem.Allocator) void {
        allocator.free(self.cwd);
        allocator.free(self.gcloud_config_path);
        self.* = undefined;
    }
};

pub fn gcpWatchScope(allocator: std.mem.Allocator, home: []const u8) !WatchScope {
    const cwd = try allocator.dupe(u8, home);
    errdefer allocator.free(cwd);
    const gcloud_config_path = try std.fmt.allocPrint(allocator, "{s}/.config/gcloud", .{home});
    errdefer allocator.free(gcloud_config_path);
    return .{
        .cwd = cwd,
        .gcloud_config_path = gcloud_config_path,
        .paths = .{.{ .path = gcloud_config_path, .recursive = true }},
    };
}

pub fn render(allocator: std.mem.Allocator, aws_profile_env: ?[]const u8, home: ?[]const u8, cache: *Cache) !?[]u8 {
    const profile = try awsProfileAlloc(allocator, aws_profile_env, home);
    defer if (profile) |value| allocator.free(value);
    const gcp_project = try cache.gcpProjectAlloc(allocator);
    defer if (gcp_project) |value| allocator.free(value);

    if (profile) |aws| if (gcp_project) |project| {
        return try std.fmt.allocPrint(allocator, "aws:{s} gcp:{s}", .{ aws, project });
    };
    if (profile) |aws| {
        return try std.fmt.allocPrint(allocator, "aws:{s}", .{aws});
    }
    if (gcp_project) |project| {
        return try std.fmt.allocPrint(allocator, "gcp:{s}", .{project});
    }
    return null;
}

test "renders aws and cached gcp context" {
    var cache = Cache{
        .valid = true,
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("aws:prod gcp:test-project", rendered);
}

test "renders cached gcp context without aws" {
    var cache = Cache{
        .valid = true,
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, null, null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("gcp:test-project", rendered);
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

const GcloudCoreJson = struct {
    project: []const u8 = "",
};

const GcloudPropertiesJson = struct {
    core: GcloudCoreJson = .{},
};

const GcloudConfigurationJson = struct {
    properties: GcloudPropertiesJson = .{},
};

const GcloudConfigHelperJson = struct {
    configuration: GcloudConfigurationJson = .{},
};

pub fn parseGcpProjectAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(GcloudConfigHelperJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const project = std.mem.trim(u8, parsed.value.configuration.properties.core.project, " \t\r\n");
    if (project.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, project));
}

fn readGcpProjectAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "gcloud", "config", "config-helper", "--format=json" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseGcpProjectAlloc(allocator, result.stdout);
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
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
    var cache = Cache{ .valid = true };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("aws:prod", rendered);
}

test "parses gcp config-helper project" {
    const project = (try parseGcpProjectAlloc(std.testing.allocator,
        \\{
        \\  "configuration": {
        \\    "properties": {
        \\      "core": {
        \\        "project": "test-project"
        \\      }
        \\    }
        \\  }
        \\}
    )).?;
    defer std.testing.allocator.free(project);
    try std.testing.expectEqualStrings("test-project", project);
}

test "builds gcp watch scope" {
    var scope = try gcpWatchScope(std.testing.allocator, "/home/me");
    defer scope.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings(module_id, scope.scope().module_id);
    try std.testing.expectEqualStrings("/home/me", scope.cwd);
    try std.testing.expectEqualStrings("/home/me/.config/gcloud", scope.gcloud_config_path);
    try std.testing.expect(scope.paths[0].recursive);
}
