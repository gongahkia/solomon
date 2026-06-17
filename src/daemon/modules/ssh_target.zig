const std = @import("std");

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
