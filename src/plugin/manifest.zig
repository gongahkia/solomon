const std = @import("std");

pub const supported_api_version: u32 = 1;

pub const Manifest = struct {
    name: []const u8,
    version: []const u8,
    api_version: u32,
    license: []const u8,
    capabilities: Capabilities = .{},
    modules: []const []const u8,
    entry_points: EntryPoints = .{},
    description: ?[]const u8 = null,
    author: ?[]const u8 = null,
    homepage: ?[]const u8 = null,
    repository: ?[]const u8 = null,

    pub fn validate(self: Manifest) !void {
        if (!isPluginName(self.name)) return error.InvalidName;
        if (!isSemver(self.version)) return error.InvalidVersion;
        if (self.api_version != supported_api_version) return error.UnsupportedApiVersion;
        if (!isSpdxLike(self.license)) return error.InvalidLicense;
        try validateModules(self.modules);
        try self.capabilities.validate();
        try self.entry_points.validate();
    }
};

pub const Capabilities = struct {
    fs_read: []const []const u8 = &.{},
    fs_watch: []const []const u8 = &.{},
    exec: ListCapability = .deny,
    net: ListCapability = .deny,
    secrets: bool = false,
    env_read: []const []const u8 = &.{},
    pre_exec: bool = false,

    pub fn validate(self: Capabilities) !void {
        try validateNonEmptyStrings(self.fs_read, error.InvalidFsRead);
        try validateNonEmptyStrings(self.fs_watch, error.InvalidFsWatch);
        try self.exec.validate(error.InvalidExecCapability);
        try self.net.validate(error.InvalidNetCapability);
        try validateEnvNames(self.env_read);
    }
};

pub const ListCapability = union(enum) {
    deny,
    allow: []const []const u8,

    fn validate(self: ListCapability, invalid_error: anyerror) !void {
        switch (self) {
            .deny => {},
            .allow => |items| try validateNonEmptyStrings(items, invalid_error),
        }
    }
};

pub const EntryPoints = struct {
    render: []const u8 = "render",
    update: ?[]const u8 = null,

    fn validate(self: EntryPoints) !void {
        if (!isLuaIdentifier(self.render)) return error.InvalidRenderEntryPoint;
        if (self.update) |name| {
            if (!isLuaIdentifier(name)) return error.InvalidUpdateEntryPoint;
        }
    }
};

fn validateModules(modules: []const []const u8) !void {
    if (modules.len == 0) return error.EmptyModules;
    for (modules, 0..) |module_id, index| {
        if (!isModuleName(module_id)) return error.InvalidModuleName;
        for (modules[0..index]) |seen| {
            if (std.mem.eql(u8, seen, module_id)) return error.DuplicateModuleName;
        }
    }
}

fn validateNonEmptyStrings(items: []const []const u8, invalid_error: anyerror) !void {
    for (items) |item| {
        if (item.len == 0) return invalid_error;
    }
}

fn validateEnvNames(items: []const []const u8) !void {
    for (items) |item| {
        if (!isEnvName(item)) return error.InvalidEnvRead;
    }
}

fn isPluginName(value: []const u8) bool {
    if (value.len == 0 or !isLowerDigit(value[0])) return false;
    for (value[1..]) |byte| {
        if (!(isLowerDigit(byte) or byte == '.' or byte == '_' or byte == '-')) return false;
    }
    return true;
}

fn isModuleName(value: []const u8) bool {
    if (value.len == 0 or !isLowerDigit(value[0])) return false;
    for (value[1..]) |byte| {
        if (!(isLowerDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn isSemver(value: []const u8) bool {
    var rest = value;
    if (!consumeNumber(&rest)) return false;
    if (!consumeByte(&rest, '.')) return false;
    if (!consumeNumber(&rest)) return false;
    if (!consumeByte(&rest, '.')) return false;
    if (!consumeNumber(&rest)) return false;
    if (rest.len == 0) return true;
    if (rest[0] != '-' and rest[0] != '+') return false;
    return isIdentifierTail(rest[1..]);
}

fn consumeNumber(rest: *[]const u8) bool {
    if (rest.*.len == 0 or !std.ascii.isDigit(rest.*[0])) return false;
    var index: usize = 0;
    while (index < rest.*.len and std.ascii.isDigit(rest.*[index])) : (index += 1) {}
    rest.* = rest.*[index..];
    return true;
}

fn consumeByte(rest: *[]const u8, byte: u8) bool {
    if (rest.*.len == 0 or rest.*[0] != byte) return false;
    rest.* = rest.*[1..];
    return true;
}

fn isSpdxLike(value: []const u8) bool {
    if (value.len == 0) return false;
    for (value) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '.' or byte == '-' or byte == '+')) return false;
    }
    return true;
}

fn isEnvName(value: []const u8) bool {
    if (value.len == 0 or !(std.ascii.isAlphabetic(value[0]) or value[0] == '_')) return false;
    for (value[1..]) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_')) return false;
    }
    return true;
}

fn isLuaIdentifier(value: []const u8) bool {
    if (value.len == 0 or !(std.ascii.isAlphabetic(value[0]) or value[0] == '_')) return false;
    for (value[1..]) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_')) return false;
    }
    return true;
}

fn isIdentifierTail(value: []const u8) bool {
    if (value.len == 0) return false;
    for (value) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '.' or byte == '-' or byte == '_')) return false;
    }
    return true;
}

fn isLowerDigit(byte: u8) bool {
    return std.ascii.isLower(byte) or std.ascii.isDigit(byte);
}

test "validates minimal manifest" {
    const manifest = Manifest{
        .name = "kubectl-context",
        .version = "0.2.1",
        .api_version = supported_api_version,
        .license = "MIT",
        .modules = &.{"k8s_ctx"},
    };
    try manifest.validate();
}

test "capabilities default to denial" {
    const capabilities = Capabilities{};
    try std.testing.expectEqual(ListCapability.deny, capabilities.exec);
    try std.testing.expectEqual(ListCapability.deny, capabilities.net);
    try std.testing.expect(!capabilities.secrets);
    try std.testing.expect(!capabilities.pre_exec);
}

test "validates granular capabilities and entry points" {
    const manifest = Manifest{
        .name = "cloud.ctx",
        .version = "1.0.0-beta",
        .api_version = supported_api_version,
        .license = "Apache-2.0",
        .capabilities = .{
            .fs_read = &.{ "~/.kube/config", "config/*.json" },
            .fs_watch = &.{"~/.kube/config"},
            .exec = .{ .allow = &.{ "kubectl", "aws" } },
            .net = .{ .allow = &.{"aws"} },
            .env_read = &.{ "KUBECONFIG", "AWS_PROFILE" },
            .pre_exec = true,
        },
        .modules = &.{ "cloud_ctx", "risk_tier" },
        .entry_points = .{ .render = "render", .update = "update" },
    };
    try manifest.validate();
}

test "rejects malformed identity fields" {
    try std.testing.expectError(error.InvalidName, (Manifest{ .name = "Bad", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{"ok"} }).validate());
    try std.testing.expectError(error.InvalidVersion, (Manifest{ .name = "ok", .version = "1.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{"ok"} }).validate());
    try std.testing.expectError(error.UnsupportedApiVersion, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = 2, .license = "MIT", .modules = &.{"ok"} }).validate());
    try std.testing.expectError(error.InvalidLicense, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT OR Apache-2.0", .modules = &.{"ok"} }).validate());
}

test "rejects malformed module and capability fields" {
    try std.testing.expectError(error.EmptyModules, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{} }).validate());
    try std.testing.expectError(error.InvalidModuleName, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{"Bad"} }).validate());
    try std.testing.expectError(error.DuplicateModuleName, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{ "same", "same" } }).validate());
    try std.testing.expectError(error.InvalidEnvRead, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .capabilities = .{ .env_read = &.{"bad-name"} }, .modules = &.{"ok"} }).validate());
    try std.testing.expectError(error.InvalidRenderEntryPoint, (Manifest{ .name = "ok", .version = "1.0.0", .api_version = supported_api_version, .license = "MIT", .modules = &.{"ok"}, .entry_points = .{ .render = "1render" } }).validate());
}
