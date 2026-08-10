const std = @import("std");
const manifest = @import("manifest.zig");

const max_state_bytes = 1024 * 1024;

pub fn pathForPluginsDirAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8) ![]u8 {
    const dir = std.fs.path.dirname(plugins_dir) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir});
}

pub fn grantName(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !void {
    if (!manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readNames(allocator, trusted_path);
    defer deinitNames(allocator, &names);
    if (indexOfString(names.items, name) == null) try names.append(allocator, try allocator.dupe(u8, name));
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writeNames(trusted_path, names.items);
}

pub fn nameIsTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !bool {
    var names = try readNames(allocator, trusted_path);
    defer deinitNames(allocator, &names);
    return indexOfString(names.items, name) != null;
}

/// A capability-free manifest is covered by an explicit name grant. Any host
/// capability additionally needs its exact fingerprint or a net-only grant.
pub fn isTrustedForManifest(allocator: std.mem.Allocator, trusted_path: []const u8, plugin_manifest: manifest.Manifest) !bool {
    if (!(try nameIsTrusted(allocator, trusted_path, plugin_manifest.name))) return false;
    if (!hasCapabilities(plugin_manifest.capabilities)) return true;

    const capabilities_path = try capabilitiesPathAlloc(allocator, trusted_path);
    defer allocator.free(capabilities_path);
    const fingerprint = try capabilityFingerprintAlloc(allocator, plugin_manifest);
    defer allocator.free(fingerprint);
    if (try capabilityFingerprintMatches(allocator, capabilities_path, plugin_manifest.name, fingerprint)) return true;
    return isTrustedByNetGrants(allocator, trusted_path, plugin_manifest);
}

pub fn grantManifest(allocator: std.mem.Allocator, trusted_path: []const u8, plugin_manifest: manifest.Manifest) !void {
    try grantName(allocator, trusted_path, plugin_manifest.name);
    if (!hasCapabilities(plugin_manifest.capabilities)) return;

    const capabilities_path = try capabilitiesPathAlloc(allocator, trusted_path);
    defer allocator.free(capabilities_path);
    const fingerprint = try capabilityFingerprintAlloc(allocator, plugin_manifest);
    defer allocator.free(fingerprint);
    try setCapabilityFingerprint(allocator, capabilities_path, plugin_manifest.name, fingerprint);
}

pub fn grantNet(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8, provider: []const u8) !void {
    if (!manifest.isValidPluginName(name)) return error.InvalidPluginName;
    if (!isValidNetProviderId(provider)) return error.InvalidNetCapability;

    const path = try netProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(path);
    var grants = try readNetGrants(allocator, path);
    defer deinitNetGrants(allocator, &grants);
    if (indexOfNetGrant(grants.items, name, provider) == null) {
        const name_copy = try allocator.dupe(u8, name);
        errdefer allocator.free(name_copy);
        const provider_copy = try allocator.dupe(u8, provider);
        errdefer allocator.free(provider_copy);
        try grants.append(allocator, .{
            .name = name_copy,
            .provider = provider_copy,
        });
    }
    std.mem.sort(NetGrant, grants.items, {}, lessThanNetGrant);
    try writeNetGrants(path, grants.items);
}

pub fn netIsTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8, provider: []const u8) !bool {
    const path = try netProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(path);
    var grants = try readNetGrants(allocator, path);
    defer deinitNetGrants(allocator, &grants);
    return indexOfNetGrant(grants.items, name, provider) != null;
}

pub fn capabilityFingerprintAlloc(allocator: std.mem.Allocator, plugin_manifest: manifest.Manifest) ![]u8 {
    var canonical: std.ArrayList(u8) = .empty;
    defer canonical.deinit(allocator);

    try appendCapabilityStringList(allocator, &canonical, "fs_read", plugin_manifest.capabilities.fs_read);
    try appendCapabilityStringList(allocator, &canonical, "fs_watch", plugin_manifest.capabilities.fs_watch);
    try appendListCapability(allocator, &canonical, "exec", plugin_manifest.capabilities.exec);
    try appendListCapability(allocator, &canonical, "net", plugin_manifest.capabilities.net);
    try appendCapabilityBool(allocator, &canonical, "secrets", plugin_manifest.capabilities.secrets);
    try appendCapabilityStringList(allocator, &canonical, "env_read", plugin_manifest.capabilities.env_read);
    try appendCapabilityBool(allocator, &canonical, "pre_exec", plugin_manifest.capabilities.pre_exec);

    var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(canonical.items, &digest, .{});
    const hex = std.fmt.bytesToHex(digest, .lower);
    return std.fmt.allocPrint(allocator, "sha256:{s}", .{hex[0..]});
}

fn hasCapabilities(capabilities: manifest.Capabilities) bool {
    return capabilities.fs_read.len != 0 or
        capabilities.fs_watch.len != 0 or
        !listCapabilityIsDeny(capabilities.exec) or
        !listCapabilityIsDeny(capabilities.net) or
        capabilities.secrets or
        capabilities.env_read.len != 0 or
        capabilities.pre_exec;
}

fn isTrustedByNetGrants(allocator: std.mem.Allocator, trusted_path: []const u8, plugin_manifest: manifest.Manifest) !bool {
    if (plugin_manifest.capabilities.fs_read.len != 0 or
        plugin_manifest.capabilities.fs_watch.len != 0 or
        !listCapabilityIsDeny(plugin_manifest.capabilities.exec) or
        plugin_manifest.capabilities.secrets or
        plugin_manifest.capabilities.env_read.len != 0 or
        plugin_manifest.capabilities.pre_exec)
    {
        return false;
    }
    return switch (plugin_manifest.capabilities.net) {
        .deny => false,
        .allow => |providers| {
            if (providers.len == 0) return false;
            for (providers) |provider| {
                if (!(try netIsTrusted(allocator, trusted_path, plugin_manifest.name, provider))) return false;
            }
            return true;
        },
    };
}

fn listCapabilityIsDeny(capability: manifest.ListCapability) bool {
    return switch (capability) {
        .deny => true,
        .allow => false,
    };
}

fn capabilitiesPathAlloc(allocator: std.mem.Allocator, trusted_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.capabilities", .{trusted_path});
}

pub fn netProvidersPathAlloc(allocator: std.mem.Allocator, trusted_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.net", .{trusted_path});
}

const NetGrant = struct {
    name: []u8,
    provider: []u8,
};

fn readNetGrants(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList(NetGrant) {
    var grants: std.ArrayList(NetGrant) = .empty;
    errdefer deinitNetGrants(allocator, &grants);
    const contents = std.fs.cwd().readFileAlloc(allocator, path, max_state_bytes) catch |err| switch (err) {
        error.FileNotFound => return grants,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const record = parseNetGrantLine(line) orelse continue;
        if (indexOfNetGrant(grants.items, record.name, record.provider) != null) continue;
        const name_copy = try allocator.dupe(u8, record.name);
        errdefer allocator.free(name_copy);
        const provider_copy = try allocator.dupe(u8, record.provider);
        errdefer allocator.free(provider_copy);
        try grants.append(allocator, .{
            .name = name_copy,
            .provider = provider_copy,
        });
    }
    return grants;
}

fn deinitNetGrants(allocator: std.mem.Allocator, grants: *std.ArrayList(NetGrant)) void {
    for (grants.items) |grant| {
        allocator.free(grant.name);
        allocator.free(grant.provider);
    }
    grants.deinit(allocator);
}

fn writeNetGrants(path: []const u8, grants: []const NetGrant) !void {
    try makeParentPath(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (grants) |grant| {
        try file.writeAll(grant.name);
        try file.writeAll(" ");
        try file.writeAll(grant.provider);
        try file.writeAll("\n");
    }
}

const NetGrantLine = struct {
    name: []const u8,
    provider: []const u8,
};

fn parseNetGrantLine(line: []const u8) ?NetGrantLine {
    var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
    const name = fields.next() orelse return null;
    const provider = fields.next() orelse return null;
    if (fields.next() != null or !manifest.isValidPluginName(name) or !isValidNetProviderId(provider)) return null;
    return .{ .name = name, .provider = provider };
}

fn isValidNetProviderId(provider: []const u8) bool {
    if (provider.len == 0) return false;
    for (provider) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '.' or byte == '_' or byte == '-')) return false;
    }
    return true;
}

fn indexOfNetGrant(grants: []const NetGrant, name: []const u8, provider: []const u8) ?usize {
    for (grants, 0..) |grant, index| {
        if (std.mem.eql(u8, grant.name, name) and std.mem.eql(u8, grant.provider, provider)) return index;
    }
    return null;
}

fn lessThanNetGrant(_: void, lhs: NetGrant, rhs: NetGrant) bool {
    if (!std.mem.eql(u8, lhs.name, rhs.name)) return std.mem.lessThan(u8, lhs.name, rhs.name);
    return std.mem.lessThan(u8, lhs.provider, rhs.provider);
}

fn appendCapabilityStringList(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, items: []const []const u8) !void {
    try appendFmt(allocator, out, "{s}:list\n", .{label});
    const sorted = try allocator.dupe([]const u8, items);
    defer allocator.free(sorted);
    std.mem.sort([]const u8, sorted, {}, lessThanString);
    for (sorted) |item| try appendFmt(allocator, out, "{s}\n", .{item});
}

fn appendListCapability(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, capability: manifest.ListCapability) !void {
    switch (capability) {
        .deny => try appendFmt(allocator, out, "{s}:deny\n", .{label}),
        .allow => |items| try appendCapabilityStringList(allocator, out, label, items),
    }
}

fn appendCapabilityBool(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, value: bool) !void {
    try appendFmt(allocator, out, "{s}:bool:{s}\n", .{ label, if (value) "true" else "false" });
}

fn capabilityFingerprintMatches(allocator: std.mem.Allocator, path: []const u8, name: []const u8, fingerprint: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, max_state_bytes) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const record = parseCapabilityLine(line) orelse continue;
        if (std.mem.eql(u8, record.name, name)) return std.mem.eql(u8, record.fingerprint, fingerprint);
    }
    return false;
}

fn setCapabilityFingerprint(allocator: std.mem.Allocator, path: []const u8, name: []const u8, fingerprint: []const u8) !void {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var replaced = false;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, max_state_bytes) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
    defer if (contents) |text| allocator.free(text);

    if (contents) |text| {
        var lines = std.mem.tokenizeScalar(u8, text, '\n');
        while (lines.next()) |line| {
            const record = parseCapabilityLine(line) orelse continue;
            if (std.mem.eql(u8, record.name, name)) {
                if (replaced) continue;
                try appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
                replaced = true;
            } else {
                try appendFmt(allocator, &out, "{s} {s}\n", .{ record.name, record.fingerprint });
            }
        }
    }
    if (!replaced) try appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
    try makeParentPath(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(out.items);
}

const CapabilityLine = struct {
    name: []const u8,
    fingerprint: []const u8,
};

fn parseCapabilityLine(line: []const u8) ?CapabilityLine {
    var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
    const name = fields.next() orelse return null;
    const fingerprint = fields.next() orelse return null;
    if (fields.next() != null or !manifest.isValidPluginName(name) or !isValidCapabilityFingerprint(fingerprint)) return null;
    return .{ .name = name, .fingerprint = fingerprint };
}

fn isValidCapabilityFingerprint(fingerprint: []const u8) bool {
    const prefix = "sha256:";
    if (!std.mem.startsWith(u8, fingerprint, prefix)) return false;
    const hex = fingerprint[prefix.len..];
    if (hex.len != std.crypto.hash.sha2.Sha256.digest_length * 2) return false;
    for (hex) |byte| {
        if (!std.ascii.isHex(byte) or std.ascii.isUpper(byte)) return false;
    }
    return true;
}

fn readNames(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList([]u8) {
    var names: std.ArrayList([]u8) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, max_state_bytes) catch |err| switch (err) {
        error.FileNotFound => return names,
        else => return err,
    };
    defer allocator.free(contents);
    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const name = std.mem.trim(u8, line, " \t\r");
        if (name.len == 0 or !manifest.isValidPluginName(name) or indexOfString(names.items, name) != null) continue;
        try names.append(allocator, try allocator.dupe(u8, name));
    }
    return names;
}

fn deinitNames(allocator: std.mem.Allocator, names: *std.ArrayList([]u8)) void {
    for (names.items) |name| allocator.free(name);
    names.deinit(allocator);
}

fn writeNames(path: []const u8, names: []const []const u8) !void {
    try makeParentPath(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (names) |name| {
        try file.writeAll(name);
        try file.writeAll("\n");
    }
}

fn makeParentPath(path: []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime fmt: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, fmt, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
}

fn indexOfString(items: []const []const u8, name: []const u8) ?usize {
    for (items, 0..) |item, index| if (std.mem.eql(u8, item, name)) return index;
    return null;
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}
