const std = @import("std");

pub const prefix = "?? ";

pub fn detectInput(input: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, input, prefix)) return null;
    return std.mem.trim(u8, input[prefix.len..], " \t\r\n");
}

test "detects nl2cmd prefix" {
    try std.testing.expectEqualStrings("list files", detectInput("?? list files").?);
    try std.testing.expectEqualStrings("", detectInput("?? ").?);
    try std.testing.expect(detectInput("echo ?? list files") == null);
    try std.testing.expect(detectInput(" ?? list files") == null);
}
