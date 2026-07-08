const std = @import("std");
const manifest = @import("manifest.zig");

pub const Error = error{ CapabilityDenied, OutOfMemory };

/// plugin-api: gate | fs_read | path | denied by default | `checkFsRead` accepts exact matches, recursive scopes ending in `/**`, `~/`, and relative plugin-dir scopes.
/// plugin-api: gate | fs_watch | path | denied by default | `checkFsWatch` uses the same path matching rules as `fs_read`.
/// plugin-api: gate | exec | command name | denied by default | `checkExec` requires an exact command allow-list match.
/// plugin-api: gate | net | provider or domain id | denied by default | `checkNet` requires an exact allow-list match.
/// plugin-api: gate | env_read | env var name | denied by default | `checkEnvRead` requires an exact environment variable allow-list match.
/// plugin-api: gate | secrets | host secret API | denied by default | `checkSecrets` requires `secrets = true`.
/// plugin-api: gate | pre_exec | pre-exec hook | denied by default | `checkPreExec` requires `pre_exec = true`.
pub const Context = struct {
    home: ?[]const u8 = null,
    plugin_dir: ?[]const u8 = null,
};

pub const HostApiCall = union(enum) {
    fs_read: []const u8,
    fs_watch: []const u8,
    exec: []const u8,
    net: []const u8,
    env_read: []const u8,
    secrets,
    pre_exec,
};

pub const Gate = struct {
    capabilities: manifest.Capabilities,
    context: Context = .{},

    pub fn init(capabilities: manifest.Capabilities, context: Context) Gate {
        return .{ .capabilities = capabilities, .context = context };
    }

    pub fn checkCall(self: Gate, call: HostApiCall) Error!void {
        return switch (call) {
            .fs_read => |path| self.checkFsRead(path),
            .fs_watch => |path| self.checkFsWatch(path),
            .exec => |command| self.checkExec(command),
            .net => |provider_or_domain| self.checkNet(provider_or_domain),
            .env_read => |name| self.checkEnvRead(name),
            .secrets => self.checkSecrets(),
            .pre_exec => self.checkPreExec(),
        };
    }

    pub fn checkFsRead(self: Gate, path: []const u8) Error!void {
        try resolveAndCheck(self.capabilities.fs_read, self.context, path);
    }

    pub fn checkFsWatch(self: Gate, path: []const u8) Error!void {
        try resolveAndCheck(self.capabilities.fs_watch, self.context, path);
    }

    pub fn checkExec(self: Gate, command: []const u8) Error!void {
        if (!listCapabilityAllows(self.capabilities.exec, command)) return error.CapabilityDenied;
    }

    pub fn checkNet(self: Gate, provider_or_domain: []const u8) Error!void {
        if (!listCapabilityAllows(self.capabilities.net, provider_or_domain)) return error.CapabilityDenied;
    }

    pub fn checkEnvRead(self: Gate, name: []const u8) Error!void {
        if (!stringListContains(self.capabilities.env_read, name)) return error.CapabilityDenied;
    }

    pub fn checkSecrets(self: Gate) Error!void {
        if (!self.capabilities.secrets) return error.CapabilityDenied;
    }

    pub fn checkPreExec(self: Gate) Error!void {
        if (!self.capabilities.pre_exec) return error.CapabilityDenied;
    }
};

fn listCapabilityAllows(capability: manifest.ListCapability, value: []const u8) bool {
    return switch (capability) {
        .deny => false,
        .allow => |items| stringListContains(items, value),
    };
}

fn stringListContains(items: []const []const u8, value: []const u8) bool {
    for (items) |item| {
        if (std.mem.eql(u8, item, value)) return true;
    }
    return false;
}

fn pathAllowed(patterns: []const []const u8, context: Context, path: []const u8) bool {
    for (patterns) |pattern| {
        if (pathPatternMatches(pattern, context, path)) return true;
    }
    return false;
}

fn resolveAndCheck(patterns: []const []const u8, context: Context, path: []const u8) Error!void {
    const real = std.fs.cwd().realpathAlloc(std.heap.page_allocator, path) catch |err| switch (err) {
        error.OutOfMemory => return error.OutOfMemory,
        else => return error.CapabilityDenied,
    };
    defer std.heap.page_allocator.free(real);
    if (!pathAllowed(patterns, context, real)) return error.CapabilityDenied;
}

fn pathPatternMatches(pattern: []const u8, context: Context, path: []const u8) bool {
    if (std.mem.startsWith(u8, pattern, "~/")) {
        const home = context.home orelse return false;
        return prefixedPatternMatches(home, pattern[1..], path);
    }
    if (std.fs.path.isAbsolute(pattern)) return singlePatternMatches(pattern, path);
    const plugin_dir = context.plugin_dir orelse return singlePatternMatches(pattern, path);
    if (!std.mem.startsWith(u8, path, plugin_dir)) return false;
    if (path.len == plugin_dir.len) return singlePatternMatches(pattern, "");
    if (!isPathSeparator(path[plugin_dir.len])) return false;
    return singlePatternMatches(pattern, path[plugin_dir.len + 1 ..]);
}

fn prefixedPatternMatches(prefix: []const u8, suffix_pattern: []const u8, path: []const u8) bool {
    if (!std.mem.startsWith(u8, path, prefix)) return false;
    return singlePatternMatches(suffix_pattern, path[prefix.len..]);
}

fn singlePatternMatches(pattern: []const u8, path: []const u8) bool {
    if (std.mem.endsWith(u8, pattern, "/**")) {
        const prefix = pattern[0 .. pattern.len - 3];
        return std.mem.eql(u8, prefix, path) or (std.mem.startsWith(u8, path, prefix) and path.len > prefix.len and isPathSeparator(path[prefix.len]));
    }
    return std.mem.eql(u8, pattern, path);
}

fn isPathSeparator(byte: u8) bool {
    return byte == '/' or byte == '\\';
}

fn recursivePatternAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/**", .{path});
}

fn makeSymlink(dir: std.fs.Dir, target_path: []const u8, link_path: []const u8) !void {
    try dir.symLink(target_path, link_path, .{});
}

test "denies omitted capabilities" {
    const gate = Gate.init(.{}, .{});

    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead("/tmp/a"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsWatch("/tmp/a"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkExec("git"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkNet("api.example.com"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkEnvRead("HOME"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkSecrets());
    try std.testing.expectError(error.CapabilityDenied, gate.checkPreExec());
}

test "host api dispatcher rejects undeclared capabilities" {
    const gate = Gate.init(.{}, .{});
    const calls = [_]HostApiCall{
        .{ .fs_read = "/tmp/a" },
        .{ .fs_watch = "/tmp/a" },
        .{ .exec = "git" },
        .{ .net = "api.example.com" },
        .{ .env_read = "HOME" },
        .secrets,
        .pre_exec,
    };

    for (calls) |call| try std.testing.expectError(error.CapabilityDenied, gate.checkCall(call));
}

test "allows scoped fs read and watch paths" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("home/project");
    try tmp.dir.makePath("plugin/assets");
    try tmp.dir.makePath("repo/.git");
    try tmp.dir.writeFile(.{ .sub_path = "home/project/config.json", .data = "{}" });
    try tmp.dir.writeFile(.{ .sub_path = "plugin/assets/icon.png", .data = "icon" });
    try tmp.dir.writeFile(.{ .sub_path = "repo/.git/HEAD", .data = "ref: refs/heads/main\n" });

    const allocator = std.testing.allocator;
    const home = try tmp.dir.realpathAlloc(allocator, "home");
    defer allocator.free(home);
    const plugin_dir = try tmp.dir.realpathAlloc(allocator, "plugin");
    defer allocator.free(plugin_dir);
    const repo_git = try tmp.dir.realpathAlloc(allocator, "repo/.git");
    defer allocator.free(repo_git);
    const home_config = try tmp.dir.realpathAlloc(allocator, "home/project/config.json");
    defer allocator.free(home_config);
    const plugin_asset = try tmp.dir.realpathAlloc(allocator, "plugin/assets/icon.png");
    defer allocator.free(plugin_asset);
    const git_head = try tmp.dir.realpathAlloc(allocator, "repo/.git/HEAD");
    defer allocator.free(git_head);
    const denied_home = try std.fs.path.join(allocator, &.{ home, ".ssh/id_ed25519" });
    defer allocator.free(denied_home);
    const denied_repo = try tmp.dir.realpathAlloc(allocator, "repo");
    defer allocator.free(denied_repo);
    const denied_repo_file = try std.fs.path.join(allocator, &.{ denied_repo, "src/main.zig" });
    defer allocator.free(denied_repo_file);
    const watch_pattern = try recursivePatternAlloc(allocator, repo_git);
    defer allocator.free(watch_pattern);
    const read_patterns = [_][]const u8{ "~/project/config.json", "assets/**" };
    const watch_patterns = [_][]const u8{watch_pattern};

    const gate = Gate.init(.{
        .fs_read = read_patterns[0..],
        .fs_watch = watch_patterns[0..],
    }, .{
        .home = home,
        .plugin_dir = plugin_dir,
    });

    try gate.checkFsRead(home_config);
    try gate.checkFsRead(plugin_asset);
    try gate.checkFsWatch(git_head);
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(denied_home));
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsWatch(denied_repo_file));
}

test "allows listed exec net env and hooks" {
    const gate = Gate.init(.{
        .exec = .{ .allow = &.{ "git", "kubectl" } },
        .net = .{ .allow = &.{ "aws", "api.example.com" } },
        .env_read = &.{ "KUBECONFIG", "AWS_PROFILE" },
        .secrets = true,
        .pre_exec = true,
    }, .{});

    try gate.checkExec("git");
    try gate.checkNet("aws");
    try gate.checkEnvRead("AWS_PROFILE");
    try gate.checkSecrets();
    try gate.checkPreExec();
    try std.testing.expectError(error.CapabilityDenied, gate.checkExec("sh"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkNet("evil.example.com"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkEnvRead("HOME"));
}

test "recursive fs scopes do not match sibling prefixes" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("repo/src");
    try tmp.dir.makePath("repo-other/src");
    try tmp.dir.writeFile(.{ .sub_path = "repo/src/main.zig", .data = "" });
    try tmp.dir.writeFile(.{ .sub_path = "repo-other/src/main.zig", .data = "" });

    const allocator = std.testing.allocator;
    const repo = try tmp.dir.realpathAlloc(allocator, "repo");
    defer allocator.free(repo);
    const allowed = try tmp.dir.realpathAlloc(allocator, "repo/src/main.zig");
    defer allocator.free(allowed);
    const sibling = try tmp.dir.realpathAlloc(allocator, "repo-other/src/main.zig");
    defer allocator.free(sibling);
    const pattern = try recursivePatternAlloc(allocator, repo);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try gate.checkFsRead(allowed);
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(sibling));
}

test "symlink pointing outside scope is denied" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("scope");
    try tmp.dir.writeFile(.{ .sub_path = "outside.txt", .data = "secret" });
    try makeSymlink(tmp.dir, "../outside.txt", "scope/link_out");

    const allocator = std.testing.allocator;
    const scope = try tmp.dir.realpathAlloc(allocator, "scope");
    defer allocator.free(scope);
    const request = try std.fs.path.join(allocator, &.{ scope, "link_out" });
    defer allocator.free(request);
    const pattern = try recursivePatternAlloc(allocator, scope);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(request));
}

test "dot-dot traversal is denied" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("scope");
    try tmp.dir.writeFile(.{ .sub_path = "outside.txt", .data = "secret" });

    const allocator = std.testing.allocator;
    const root = try tmp.dir.realpathAlloc(allocator, ".");
    defer allocator.free(root);
    const scope = try tmp.dir.realpathAlloc(allocator, "scope");
    defer allocator.free(scope);
    const request = try std.fs.path.join(allocator, &.{ root, "scope", "..", "outside.txt" });
    defer allocator.free(request);
    const pattern = try recursivePatternAlloc(allocator, scope);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(request));
}

test "nested symlink chain outside scope is denied" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("scope");
    try tmp.dir.writeFile(.{ .sub_path = "outside.txt", .data = "secret" });
    try makeSymlink(tmp.dir, "../outside.txt", "scope/link_b");
    try makeSymlink(tmp.dir, "link_b", "scope/link_a");

    const allocator = std.testing.allocator;
    const scope = try tmp.dir.realpathAlloc(allocator, "scope");
    defer allocator.free(scope);
    const request = try std.fs.path.join(allocator, &.{ scope, "link_a" });
    defer allocator.free(request);
    const pattern = try recursivePatternAlloc(allocator, scope);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(request));
}

test "symlink to allowed file inside scope is permitted" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("scope");
    try tmp.dir.writeFile(.{ .sub_path = "scope/allowed.txt", .data = "ok" });
    try makeSymlink(tmp.dir, "allowed.txt", "scope/link_in");

    const allocator = std.testing.allocator;
    const scope = try tmp.dir.realpathAlloc(allocator, "scope");
    defer allocator.free(scope);
    const request = try std.fs.path.join(allocator, &.{ scope, "link_in" });
    defer allocator.free(request);
    const pattern = try recursivePatternAlloc(allocator, scope);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try gate.checkFsRead(request);
}

test "hostile plugin traversal requests are denied without side effects" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("scope");
    try tmp.dir.writeFile(.{ .sub_path = "outside.txt", .data = "clean" });

    const allocator = std.testing.allocator;
    const root = try tmp.dir.realpathAlloc(allocator, ".");
    defer allocator.free(root);
    const scope = try tmp.dir.realpathAlloc(allocator, "scope");
    defer allocator.free(scope);
    const request = try std.fs.path.join(allocator, &.{ root, "scope", "..", "outside.txt" });
    defer allocator.free(request);
    const pattern = try recursivePatternAlloc(allocator, scope);
    defer allocator.free(pattern);
    const read_patterns = [_][]const u8{pattern};
    const gate = Gate.init(.{ .fs_read = read_patterns[0..] }, .{});

    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead(request));
    const contents = try tmp.dir.readFileAlloc(allocator, "outside.txt", 64);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("clean", contents);
}
