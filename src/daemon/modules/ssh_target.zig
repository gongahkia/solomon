const std = @import("std");
const risk_tier = @import("risk_tier.zig");

pub const module_id = "ssh_target";

pub fn insideSsh(ssh_connection: ?[]const u8) bool {
    const value = ssh_connection orelse return false;
    return std.mem.trim(u8, value, " \t\r\n").len != 0;
}

pub fn targetHostAlloc(allocator: std.mem.Allocator, ssh_connection: ?[]const u8, host: []const u8) !?[]u8 {
    if (!insideSsh(ssh_connection)) return null;
    const trimmed = std.mem.trim(u8, host, " \t\r\n");
    if (trimmed.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, trimmed));
}

pub fn classifyHost(host: []const u8, rules: ?risk_tier.Rules) risk_tier.Tier {
    return if (rules) |loaded| risk_tier.classifyWithRules(host, loaded) else risk_tier.classify(host);
}

pub fn classifyHostWithUserRules(allocator: std.mem.Allocator, home: ?[]const u8, host: []const u8) !risk_tier.Tier {
    var rules = try risk_tier.loadUserRulesAlloc(allocator, home);
    defer if (rules) |*loaded| loaded.deinit(allocator);
    return classifyHost(host, rules);
}

pub fn render(allocator: std.mem.Allocator, ssh_connection: ?[]const u8, host: []const u8, home: ?[]const u8) !?[]u8 {
    const target = (try targetHostAlloc(allocator, ssh_connection, host)) orelse return null;
    defer allocator.free(target);
    const tier = try classifyHostWithUserRules(allocator, home, target);
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "→ {s} ({s})", .{ target, risk_tier.tierName(tier) }));
}

test "detects ssh connection env" {
    try std.testing.expect(insideSsh("192.0.2.1 55555 198.51.100.2 22"));
    try std.testing.expect(!insideSsh(null));
    try std.testing.expect(!insideSsh(" \n"));
}

test "returns target host only inside ssh" {
    const host = (try targetHostAlloc(std.testing.allocator, "192.0.2.1 55555 198.51.100.2 22", "prod-bastion")).?;
    defer std.testing.allocator.free(host);
    try std.testing.expectEqualStrings("prod-bastion", host);
    try std.testing.expect(try targetHostAlloc(std.testing.allocator, null, "prod-bastion") == null);
}

test "classifies ssh target host" {
    try std.testing.expectEqual(risk_tier.Tier.prod, classifyHost("prod-bastion", null));
    try std.testing.expectEqual(risk_tier.Tier.staging, classifyHost("api-staging-1", null));
    try std.testing.expectEqual(risk_tier.Tier.unknown, classifyHost("host", null));
}

test "renders ssh target segment" {
    const segment = (try render(std.testing.allocator, "192.0.2.1 55555 198.51.100.2 22", "prod-bastion", null)).?;
    defer std.testing.allocator.free(segment);
    try std.testing.expectEqualStrings("→ prod-bastion (prod)", segment);
    try std.testing.expect(try render(std.testing.allocator, null, "prod-bastion", null) == null);
}
