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

pub const Options = struct {
    aws: bool = true,
    gcp: bool = true,
    azure: bool = true,
    kubernetes: bool = true,
};

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    gcp_valid: bool = false,
    gcp_path: ?[]u8 = null,
    gcp_project: ?[]u8 = null,
    azure_valid: bool = false,
    azure_path: ?[]u8 = null,
    azure_subscription: ?[]u8 = null,
    kube_valid: bool = false,
    kube_path: ?[]u8 = null,
    kube_context: ?[]u8 = null,

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

    pub fn invalidateKube(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearKubeLocked(allocator);
    }

    pub fn gcpProjectAlloc(self: *Cache, allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
        const path = (try gcpConfigPathAlloc(allocator, home)) orelse return null;
        defer allocator.free(path);

        self.mutex.lock();
        if (self.gcp_valid and self.gcp_path != null and std.mem.eql(u8, self.gcp_path.?, path)) {
            const project = if (self.gcp_project) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return project;
        }
        self.mutex.unlock();

        const project = try readGcpProjectAlloc(allocator, path);
        errdefer if (project) |value| allocator.free(value);
        const cached_path = try allocator.dupe(u8, path);
        errdefer allocator.free(cached_path);
        const cached_project = if (project) |value| try allocator.dupe(u8, value) else null;
        errdefer if (cached_project) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearGcpLocked(allocator);
        self.gcp_path = cached_path;
        self.gcp_project = cached_project;
        self.gcp_valid = true;
        return project;
    }

    pub fn azureSubscriptionAlloc(self: *Cache, allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
        const path = (try azureProfilePathAlloc(allocator, home)) orelse return null;
        defer allocator.free(path);

        self.mutex.lock();
        if (self.azure_valid and self.azure_path != null and std.mem.eql(u8, self.azure_path.?, path)) {
            const subscription = if (self.azure_subscription) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return subscription;
        }
        self.mutex.unlock();

        const subscription = try readAzureSubscriptionAlloc(allocator, path);
        errdefer if (subscription) |value| allocator.free(value);
        const cached_path = try allocator.dupe(u8, path);
        errdefer allocator.free(cached_path);
        const cached_subscription = if (subscription) |value| try allocator.dupe(u8, value) else null;
        errdefer if (cached_subscription) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearAzureLocked(allocator);
        self.azure_path = cached_path;
        self.azure_subscription = cached_subscription;
        self.azure_valid = true;
        return subscription;
    }

    pub fn kubeContextAlloc(self: *Cache, allocator: std.mem.Allocator, kubeconfig_env: ?[]const u8, home: ?[]const u8) !?[]u8 {
        const path = (try kubeConfigPathAlloc(allocator, kubeconfig_env, home)) orelse return null;
        defer allocator.free(path);

        self.mutex.lock();
        if (self.kube_valid and self.kube_path != null and std.mem.eql(u8, self.kube_path.?, path)) {
            const context = if (self.kube_context) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return context;
        }
        self.mutex.unlock();

        const context = try readKubeContextAlloc(allocator, path);
        errdefer if (context) |value| allocator.free(value);
        const cached_path = try allocator.dupe(u8, path);
        errdefer allocator.free(cached_path);
        const cached_context = if (context) |value| try allocator.dupe(u8, value) else null;
        errdefer if (cached_context) |value| allocator.free(value);

        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearKubeLocked(allocator);
        self.kube_path = cached_path;
        self.kube_context = cached_context;
        self.kube_valid = true;
        return context;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clearLocked(allocator);
    }

    fn clearLocked(self: *Cache, allocator: std.mem.Allocator) void {
        self.clearGcpLocked(allocator);
        self.clearAzureLocked(allocator);
        self.clearKubeLocked(allocator);
    }

    fn clearGcpLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.gcp_path) |value| allocator.free(value);
        if (self.gcp_project) |value| allocator.free(value);
        self.gcp_path = null;
        self.gcp_project = null;
        self.gcp_valid = false;
    }

    fn clearAzureLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.azure_path) |value| allocator.free(value);
        if (self.azure_subscription) |value| allocator.free(value);
        self.azure_path = null;
        self.azure_subscription = null;
        self.azure_valid = false;
    }

    fn clearKubeLocked(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.kube_path) |value| allocator.free(value);
        if (self.kube_context) |value| allocator.free(value);
        self.kube_path = null;
        self.kube_context = null;
        self.kube_valid = false;
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

pub fn kubeWatchScope(allocator: std.mem.Allocator, kubeconfig_env: ?[]const u8, home: ?[]const u8) !?WatchScope {
    const kubeconfig_path = (try kubeConfigPathAlloc(allocator, kubeconfig_env, home)) orelse return null;
    errdefer allocator.free(kubeconfig_path);
    const cwd = try allocator.dupe(u8, kubeconfig_path);
    errdefer allocator.free(cwd);
    return .{
        .cwd = cwd,
        .watched_path = kubeconfig_path,
        .paths = .{.{ .path = kubeconfig_path }},
    };
}

pub fn render(allocator: std.mem.Allocator, aws_profile_env: ?[]const u8, kubeconfig_env: ?[]const u8, home: ?[]const u8, cache: *Cache, options: Options) !?[]u8 {
    const profile = if (options.aws) try awsProfileAlloc(allocator, aws_profile_env, home) else null;
    defer if (profile) |value| allocator.free(value);
    const gcp_project = if (options.gcp) try cache.gcpProjectAlloc(allocator, home) else null;
    defer if (gcp_project) |value| allocator.free(value);
    const azure_subscription = if (options.azure) try cache.azureSubscriptionAlloc(allocator, home) else null;
    defer if (azure_subscription) |value| allocator.free(value);
    const kube_context = if (options.kubernetes) try cache.kubeContextAlloc(allocator, kubeconfig_env, home) else null;
    defer if (kube_context) |value| allocator.free(value);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    if (profile) |aws| try appendCloudSegment(allocator, &out, "aws", aws);
    if (gcp_project) |project| try appendCloudSegment(allocator, &out, "gcp", project);
    if (azure_subscription) |subscription| try appendCloudSegment(allocator, &out, "az", subscription);
    if (kube_context) |context| try appendCloudSegment(allocator, &out, "k8s", context);
    if (out.items.len == 0) return null;
    return try std.fmt.allocPrint(allocator, "cloud[{s}]", .{out.items});
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

pub fn parseGcpProjectAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var in_core = false;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#' or line[0] == ';') continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            const section = std.mem.trim(u8, line[1 .. line.len - 1], " \t");
            in_core = std.mem.eql(u8, section, "core");
            continue;
        }
        if (!in_core) continue;
        const value = iniValue(line, "project") orelse continue;
        if (value.len != 0) return @as(?[]u8, try allocator.dupe(u8, value));
    }
    return null;
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

const AzureSubscriptionJson = struct {
    name: []const u8 = "",
    id: []const u8 = "",
    isDefault: bool = false,
};

const AzureProfileJson = struct {
    subscriptions: ?[]AzureSubscriptionJson = null,
};

pub fn parseAzureSubscriptionAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AzureProfileJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const subscriptions = parsed.value.subscriptions orelse return null;
    var fallback: ?AzureSubscriptionJson = null;
    for (subscriptions) |subscription| {
        if (fallback == null) fallback = subscription;
        if (subscription.isDefault) {
            const selected = try dupeAzureSubscriptionName(allocator, subscription);
            if (selected != null) return selected;
        }
    }
    if (fallback) |subscription| return dupeAzureSubscriptionName(allocator, subscription);
    return null;
}

pub fn azureProfilePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.azure/azureProfile.json", .{home_path}));
}

pub fn kubeConfigPathAlloc(allocator: std.mem.Allocator, kubeconfig_env: ?[]const u8, home: ?[]const u8) !?[]u8 {
    if (kubeconfig_env) |value| {
        var entries = std.mem.splitScalar(u8, value, std.fs.path.delimiter);
        while (entries.next()) |entry| {
            const trimmed = std.mem.trim(u8, entry, " \t\r\n");
            if (trimmed.len != 0) return @as(?[]u8, try allocator.dupe(u8, trimmed));
        }
    }
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.kube/config", .{home_path}));
}

pub fn parseKubeContextAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    const current_context = findTopLevelYamlScalar(source, "current-context") orelse return null;
    const namespace = findKubeNamespace(source, current_context);
    if (namespace) |value| {
        if (value.len != 0) return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/{s}", .{ current_context, value }));
    }
    return @as(?[]u8, try allocator.dupe(u8, current_context));
}

fn readAzureSubscriptionAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAzureSubscriptionAlloc(allocator, source);
}

fn readKubeContextAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseKubeContextAlloc(allocator, source);
}

fn appendCloudSegment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), provider: []const u8, value: []const u8) !void {
    if (out.items.len != 0) try out.append(allocator, ' ');
    try std.fmt.format(out.writer(allocator), "{s}:{s}", .{ provider, value });
}

fn readGcpProjectAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseGcpProjectAlloc(allocator, source);
}

fn iniValue(line: []const u8, key: []const u8) ?[]const u8 {
    const eq_index = std.mem.indexOfScalar(u8, line, '=') orelse return null;
    const parsed_key = std.mem.trim(u8, line[0..eq_index], " \t");
    if (!std.mem.eql(u8, parsed_key, key)) return null;
    return std.mem.trim(u8, line[eq_index + 1 ..], " \t\r\n");
}

fn safeGcloudConfigName(name: []const u8) bool {
    for (name) |byte| {
        if (byte == '/' or byte == '\\' or byte == 0) return false;
    }
    return true;
}

fn dupeAzureSubscriptionName(allocator: std.mem.Allocator, subscription: AzureSubscriptionJson) !?[]u8 {
    const name = std.mem.trim(u8, subscription.name, " \t\r\n");
    if (name.len != 0) return @as(?[]u8, try allocator.dupe(u8, name));
    const id = std.mem.trim(u8, subscription.id, " \t\r\n");
    if (id.len != 0) return @as(?[]u8, try allocator.dupe(u8, id));
    return null;
}

const YamlLine = struct {
    indent: usize,
    trimmed: []const u8,
};

fn yamlLine(raw_line: []const u8) ?YamlLine {
    const line = std.mem.trimRight(u8, raw_line, "\r");
    const trimmed = std.mem.trim(u8, line, " \t");
    if (trimmed.len == 0 or trimmed[0] == '#') return null;
    var indent: usize = 0;
    while (indent < line.len and line[indent] == ' ') : (indent += 1) {}
    return .{ .indent = indent, .trimmed = trimmed };
}

fn hasYamlKey(line: []const u8, key: []const u8) bool {
    return line.len > key.len and std.mem.startsWith(u8, line, key) and line[key.len] == ':';
}

fn yamlScalar(line: []const u8, key: []const u8) ?[]const u8 {
    if (!hasYamlKey(line, key)) return null;
    var value = std.mem.trim(u8, line[key.len + 1 ..], " \t\r\n");
    if (value.len >= 2 and ((value[0] == '"' and value[value.len - 1] == '"') or (value[0] == '\'' and value[value.len - 1] == '\''))) {
        value = value[1 .. value.len - 1];
    }
    return value;
}

fn findTopLevelYamlScalar(source: []const u8, key: []const u8) ?[]const u8 {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = yamlLine(raw_line) orelse continue;
        if (line.indent != 0) continue;
        const value = yamlScalar(line.trimmed, key) orelse continue;
        if (value.len != 0) return value;
    }
    return null;
}

fn findKubeNamespace(source: []const u8, current_context: []const u8) ?[]const u8 {
    var lines = std.mem.splitScalar(u8, source, '\n');
    var in_contexts = false;
    var contexts_indent: usize = 0;
    var entry_active = false;
    var entry_indent: usize = 0;
    var context_indent: ?usize = null;
    var entry_name: ?[]const u8 = null;
    var entry_namespace: ?[]const u8 = null;

    while (lines.next()) |raw_line| {
        const line = yamlLine(raw_line) orelse continue;
        if (!in_contexts) {
            if (line.indent == 0 and hasYamlKey(line.trimmed, "contexts")) {
                in_contexts = true;
                contexts_indent = line.indent;
            }
            continue;
        }

        if (line.indent <= contexts_indent and !std.mem.startsWith(u8, line.trimmed, "- ")) break;
        if (std.mem.startsWith(u8, line.trimmed, "- ")) {
            if (entry_active and entry_name != null and std.mem.eql(u8, entry_name.?, current_context)) return entry_namespace;
            entry_active = true;
            entry_indent = line.indent;
            context_indent = null;
            entry_name = null;
            entry_namespace = null;
            const rest = std.mem.trim(u8, line.trimmed[2..], " \t");
            if (yamlScalar(rest, "name")) |value| entry_name = value;
            if (hasYamlKey(rest, "context")) context_indent = line.indent;
            if (yamlScalar(rest, "namespace")) |value| entry_namespace = value;
            continue;
        }

        if (!entry_active or line.indent <= entry_indent) continue;
        if (yamlScalar(line.trimmed, "name")) |value| entry_name = value;
        if (hasYamlKey(line.trimmed, "context")) {
            context_indent = line.indent;
            continue;
        }
        if (context_indent) |indent| {
            if (line.indent > indent) {
                if (yamlScalar(line.trimmed, "namespace")) |value| entry_namespace = value;
            } else {
                context_indent = null;
            }
        }
    }

    if (entry_active and entry_name != null and std.mem.eql(u8, entry_name.?, current_context)) return entry_namespace;
    return null;
}

test "aws profile env wins" {
    const profile = (try awsProfileAlloc(std.testing.allocator, " prod ", null)).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("prod", profile);
}

test "parses default aws config profile" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/aws-config-default");
    defer std.testing.allocator.free(source);
    const profile = (try parseAwsConfigProfileAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("default", profile);
}

test "parses first named aws config profile" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/aws-config-named");
    defer std.testing.allocator.free(source);
    const profile = (try parseAwsConfigProfileAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(profile);
    try std.testing.expectEqualStrings("staging", profile);
}

test "renders aws cloud context" {
    var cache = Cache{ .gcp_valid = true, .azure_valid = true, .kube_valid = true };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", null, null, &cache, .{})).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("cloud[aws:prod]", rendered);
}

test "renders cached cloud contexts" {
    var cache = Cache{
        .gcp_valid = true,
        .gcp_path = try std.testing.allocator.dupe(u8, "/home/me/.config/gcloud/configurations/config_default"),
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
        .azure_valid = true,
        .azure_path = try std.testing.allocator.dupe(u8, "/home/me/.azure/azureProfile.json"),
        .azure_subscription = try std.testing.allocator.dupe(u8, "prod-sub"),
        .kube_valid = true,
        .kube_path = try std.testing.allocator.dupe(u8, "/tmp/kubeconfig"),
        .kube_context = try std.testing.allocator.dupe(u8, "prod/default"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", "/tmp/kubeconfig", "/home/me", &cache, .{})).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("cloud[aws:prod gcp:test-project az:prod-sub k8s:prod/default]", rendered);
}

test "renders cached gcp context without aws" {
    var cache = Cache{
        .gcp_valid = true,
        .gcp_path = try std.testing.allocator.dupe(u8, "/home/me/.config/gcloud/configurations/config_default"),
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
        .azure_valid = true,
        .azure_path = try std.testing.allocator.dupe(u8, "/home/me/.azure/azureProfile.json"),
        .kube_valid = true,
        .kube_path = try std.testing.allocator.dupe(u8, "/home/me/.kube/config"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, null, null, "/home/me", &cache, .{})).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("cloud[gcp:test-project]", rendered);
}

test "hides disabled cloud providers" {
    var cache = Cache{
        .gcp_valid = true,
        .gcp_path = try std.testing.allocator.dupe(u8, "/home/me/.config/gcloud/configurations/config_default"),
        .gcp_project = try std.testing.allocator.dupe(u8, "test-project"),
        .azure_valid = true,
        .azure_path = try std.testing.allocator.dupe(u8, "/home/me/.azure/azureProfile.json"),
        .azure_subscription = try std.testing.allocator.dupe(u8, "prod-sub"),
        .kube_valid = true,
        .kube_path = try std.testing.allocator.dupe(u8, "/tmp/kubeconfig"),
        .kube_context = try std.testing.allocator.dupe(u8, "prod/default"),
    };
    defer cache.deinit(std.testing.allocator);
    const rendered = (try render(std.testing.allocator, "prod", "/tmp/kubeconfig", "/home/me", &cache, .{ .aws = false, .azure = false })).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("cloud[gcp:test-project k8s:prod/default]", rendered);
}

test "parses gcp config project" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/gcloud-config");
    defer std.testing.allocator.free(source);
    const project = (try parseGcpProjectAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(project);
    try std.testing.expectEqualStrings("test-project", project);
}

test "parses azure subscription" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/azureProfile.json");
    defer std.testing.allocator.free(source);
    const subscription = (try parseAzureSubscriptionAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(subscription);
    try std.testing.expectEqualStrings("prod-sub", subscription);
}

test "resolves default gcp config path" {
    const path = (try gcpConfigPathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.config/gcloud/configurations/config_default", path);
}

test "resolves azure profile path" {
    const path = (try azureProfilePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.azure/azureProfile.json", path);
}

test "resolves kubeconfig path from env list" {
    const path = (try kubeConfigPathAlloc(std.testing.allocator, " /tmp/kube-a:/tmp/kube-b ", "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/kube-a", path);
}

test "resolves default kubeconfig path" {
    const path = (try kubeConfigPathAlloc(std.testing.allocator, null, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.kube/config", path);
}

test "parses kube context and namespace" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/kubeconfig-with-namespace.yaml");
    defer std.testing.allocator.free(source);
    const context = (try parseKubeContextAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(context);
    try std.testing.expectEqualStrings("prod/default", context);
}

test "parses kube context without namespace" {
    const source = try readFixtureAlloc(std.testing.allocator, "test/fixtures/cloud/kubeconfig-no-namespace.yaml");
    defer std.testing.allocator.free(source);
    const context = (try parseKubeContextAlloc(std.testing.allocator, source)).?;
    defer std.testing.allocator.free(context);
    try std.testing.expectEqualStrings("prod", context);
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

test "builds kube watch scope" {
    var scope = (try kubeWatchScope(std.testing.allocator, "/tmp/kubeconfig", "/home/me")).?;
    defer scope.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings(module_id, scope.scope().module_id);
    try std.testing.expectEqualStrings("/tmp/kubeconfig", scope.cwd);
    try std.testing.expectEqualStrings("/tmp/kubeconfig", scope.watched_path);
    try std.testing.expect(!scope.paths[0].recursive);
}

fn readFixtureAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    return std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024);
}
