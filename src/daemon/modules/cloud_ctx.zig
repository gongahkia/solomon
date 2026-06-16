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
    gcp_valid: bool = false,
    gcp_project: ?[]u8 = null,
    azure_valid: bool = false,
    azure_subscription: ?[]u8 = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn invalidateGcp(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearGcpLocked(allocator);
    }

    pub fn invalidateAzure(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearAzureLocked(allocator);
    }

    pub fn gcpProjectAlloc(self: *Cache, allocator: std.mem.Allocator) !?[]u8 {
        self.mutex.lock();
        if (self.gcp_valid) {
            const project = if (self.gcp_project) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return project;
        }
        self.mutex.unlock();

        const project = try readGcpProjectAlloc(allocator);
        errdefer if (project) |value| allocator.free(value);
        const cached_project = if (project) |value| try allocator.dupe(u8, value) else null;
        errdefer if (cached_project) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearGcpLocked(allocator);
        self.gcp_project = cached_project;
        self.gcp_valid = true;
        return project;
    }

    pub fn azureSubscriptionAlloc(self: *Cache, allocator: std.mem.Allocator) !?[]u8 {
        self.mutex.lock();
        if (self.azure_valid) {
            const subscription = if (self.azure_subscription) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return subscription;
        }
        self.mutex.unlock();

        const subscription = try readAzureSubscriptionAlloc(allocator);
        errdefer if (subscription) |value| allocator.free(value);
        const cached_subscription = if (subscription) |value| try allocator.dupe(u8, value) else null;
        errdefer if (cached_subscription) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearAzureLocked(allocator);
        self.azure_subscription = cached_subscription;
        self.azure_valid = true;
        return subscription;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearLocked(allocator);
    }

    fn clearLocked(self: *Cache, allocator: std.mem.Allocator) void {
        self.clearGcpLocked(allocator);
        self.clearAzureLocked(allocator);
    }

    fn clearGcpLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.gcp_project) |value| allocator.free(value);
        self.gcp_project = null;
        self.gcp_valid = false;
    }

    fn clearAzureLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.azure_subscription) |value| allocator.free(value);
        self.azure_subscription = null;
        self.azure_valid = false;
    }
};

pub const WatchScope = struct {
    cwd: []u8,
    watched_path: []u8,
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
        allocator.free(self.watched_path);
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
        .watched_path = gcloud_config_path,
        .paths = .{.{ .path = gcloud_config_path, .recursive = true }},
    };
}

pub fn azureWatchScope(allocator: std.mem.Allocator, home: []const u8) !WatchScope {
    const azure_profile_path = try std.fmt.allocPrint(allocator, "{s}/.azure/azureProfile.json", .{home});
    errdefer allocator.free(azure_profile_path);
    const cwd = try allocator.dupe(u8, azure_profile_path);
    errdefer allocator.free(cwd);
    return .{
        .cwd = cwd,
        .watched_path = azure_profile_path,
        .paths = .{.{ .path = azure_profile_path }},
    };
}

pub fn render(allocator: std.mem.Allocator, aws_profile_env: ?[]const u8, home: ?[]const u8, cache: *Cache) !?[]u8 {
    const profile = try awsProfileAlloc(allocator, aws_profile_env, home);
    defer if (profile) |value| allocator.free(value);
    const gcp_project = try cache.gcpProjectAlloc(allocator);
    defer if (gcp_project) |value| allocator.free(value);
    const azure_subscription = try cache.azureSubscriptionAlloc(allocator);
    defer if (azure_subscription) |value| allocator.free(value);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    if (profile) |aws| try appendCloudSegment(allocator, &out, "aws", aws);
    if (gcp_project) |project| try appendCloudSegment(allocator, &out, "gcp", project);
    if (azure_subscription) |subscription| try appendCloudSegment(allocator, &out, "azure", subscription);
    if (out.items.len == 0) return null;
    return try out.toOwnedSlice(allocator);
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

const AzureAccountJson = struct {
    name: []const u8 = "",
    id: []const u8 = "",
};

pub fn parseAzureSubscriptionAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AzureAccountJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const name = std.mem.trim(u8, parsed.value.name, " \t\r\n");
    if (name.len != 0) return @as(?[]u8, try allocator.dupe(u8, name));
    const id = std.mem.trim(u8, parsed.value.id, " \t\r\n");
    if (id.len != 0) return @as(?[]u8, try allocator.dupe(u8, id));
    return null;
}

fn readAzureSubscriptionAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "az", "account", "show", "--output", "json" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseAzureSubscriptionAlloc(allocator, result.stdout);
}

fn appendCloudSegment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), provider: []const u8, value: []const u8) !void {
    if (out.items.len != 0) try out.append(allocator, ' ');
    try std.fmt.format(out.writer(allocator), "{s}:{s}", .{ provider, value });
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
    var cache = Cache{ .gcp_valid = true, .azure_valid = true };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("aws:prod", rendered);
}

test "renders cached cloud contexts" {
    var cache = Cache{
        .gcp_valid = true,
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
        .azure_valid = true,
        .azure_subscription = try std.testing.allocator.dupe(u8, "prod-sub"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("aws:prod gcp:test-project azure:prod-sub", rendered);
}

test "renders cached gcp context without aws" {
    var cache = Cache{
        .gcp_valid = true,
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
        .azure_valid = true,
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, null, null, &cache)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("gcp:test-project", rendered);
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

test "parses azure subscription" {
    const subscription = (try parseAzureSubscriptionAlloc(std.testing.allocator,
        \\{
        \\  "id": "00000000-0000-0000-0000-000000000000",
        \\  "name": "prod-sub"
        \\}
    )).?;
    defer std.testing.allocator.free(subscription);
    try std.testing.expectEqualStrings("prod-sub", subscription);
}

test "builds gcp watch scope" {
    var scope = try gcpWatchScope(std.testing.allocator, "/home/me");
    defer scope.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings(module_id, scope.scope().module_id);
    try std.testing.expectEqualStrings("/home/me", scope.cwd);
    try std.testing.expectEqualStrings("/home/me/.config/gcloud", scope.watched_path);
    try std.testing.expect(scope.paths[0].recursive);
}

test "builds azure watch scope" {
    var scope = try azureWatchScope(std.testing.allocator, "/home/me");
    defer scope.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings(module_id, scope.scope().module_id);
    try std.testing.expectEqualStrings("/home/me/.azure/azureProfile.json", scope.cwd);
    try std.testing.expectEqualStrings("/home/me/.azure/azureProfile.json", scope.watched_path);
    try std.testing.expect(!scope.paths[0].recursive);
}
