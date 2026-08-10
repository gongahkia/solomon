const std = @import("std");
const builtin = @import("builtin");

pub fn enforceOwnerOnly(path: []const u8) !void {
    if (comptime builtin.os.tag == .windows) return;
    try std.posix.fchmodat(std.fs.cwd().fd, path, 0o600, 0);
}

pub fn isOwnerOnly(mode: usize) bool {
    return (mode & 0o777) == 0o600;
}

test "owner-only socket modes require exactly 0600" {
    try std.testing.expect(isOwnerOnly(0o600));
    try std.testing.expect(!isOwnerOnly(0o660));
    try std.testing.expect(!isOwnerOnly(0o644));
    try std.testing.expect(!isOwnerOnly(0o700));
}

test "enforce owner-only mode" {
    if (comptime builtin.os.tag == .windows) return;

    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(.{ .sub_path = "socket", .data = "" });
    const path = try tmp.dir.realpathAlloc(std.testing.allocator, "socket");
    defer std.testing.allocator.free(path);

    try enforceOwnerOnly(path);
    const stat = try std.fs.cwd().statFile(path);
    try std.testing.expect(isOwnerOnly(stat.mode));
}
