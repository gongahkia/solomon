const std = @import("std");

pub fn escapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    for (value) |byte| {
        switch (byte) {
            '"' => try out.appendSlice(allocator, "\\\""),
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }

    return out.toOwnedSlice(allocator);
}

test "escapes json string content" {
    const escaped = try escapeAlloc(std.testing.allocator, "a\"b\\c\n");
    defer std.testing.allocator.free(escaped);
    try std.testing.expectEqualStrings("a\\\"b\\\\c\\n", escaped);
}
