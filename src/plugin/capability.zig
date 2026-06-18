const std = @import("std");
const manifest = @import("manifest.zig");

pub const Error = error{CapabilityDenied};

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
        if (!pathAllowed(self.capabilities.fs_read, self.context, path)) return error.CapabilityDenied;
    }

    pub fn checkFsWatch(self: Gate, path: []const u8) Error!void {
        if (!pathAllowed(self.capabilities.fs_watch, self.context, path)) return error.CapabilityDenied;
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

test "allows scoped fs read and watch paths" {
    const gate = Gate.init(.{
        .fs_read = &.{ "~/project/config.json", "assets/**" },
        .fs_watch = &.{"/repo/.git/**"},
    }, .{
        .home = "/Users/alice",
        .plugin_dir = "/Users/alice/.config/shisa/plugins/kube",
    });

    try gate.checkFsRead("/Users/alice/project/config.json");
    try gate.checkFsRead("/Users/alice/.config/shisa/plugins/kube/assets/icon.png");
    try gate.checkFsWatch("/repo/.git/HEAD");
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead("/Users/alice/.ssh/id_ed25519"));
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsWatch("/repo/src/main.zig"));
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
    const gate = Gate.init(.{
        .fs_read = &.{"/repo/**"},
    }, .{});

    try gate.checkFsRead("/repo/src/main.zig");
    try std.testing.expectError(error.CapabilityDenied, gate.checkFsRead("/repo-other/src/main.zig"));
}
