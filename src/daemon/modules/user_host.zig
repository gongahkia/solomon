const std = @import("std");

pub fn render(allocator: std.mem.Allocator, ssh_connection: ?[]const u8, user: []const u8, host: []const u8) !?[]u8 {
    const ssh = ssh_connection orelse return null;
    if (ssh.len == 0) return null;
    return try std.fmt.allocPrint(allocator, "{s}@{s}", .{ user, host });
}

test "hides outside ssh" {
    try std.testing.expect(try render(std.testing.allocator, null, "me", "host") == null);
}

test "renders user and host in ssh" {
    const rendered = (try render(std.testing.allocator, "1 2 3 4", "me", "host")).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("me@host", rendered);
}
