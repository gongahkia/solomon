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
            0...0x08, 0x0b...0x0c, 0x0e...0x1f, 0x7f => {
                var escaped: [6]u8 = undefined;
                const slice = try std.fmt.bufPrint(&escaped, "\\u00{x:0>2}", .{byte});
                try out.appendSlice(allocator, slice);
            },
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

test "escapes ansi control byte" {
    const escaped = try escapeAlloc(std.testing.allocator, "\x1b[31m");
    defer std.testing.allocator.free(escaped);
    try std.testing.expectEqualStrings("\\u001b[31m", escaped);
}

test "escapes json control byte edge cases" {
    inline for (.{
        .{ "\x00", "\\u0000" },
        .{ "\x08", "\\u0008" },
        .{ "\x0c", "\\u000c" },
        .{ "\x7f", "\\u007f" },
    }) |case| {
        const escaped = try escapeAlloc(std.testing.allocator, case[0]);
        defer std.testing.allocator.free(escaped);
        try std.testing.expectEqualStrings(case[1], escaped);
    }
}

test "escapes full json-required control range" {
    for (0..0x20) |value| {
        const byte: u8 = @intCast(value);
        const escaped = try escapeAlloc(std.testing.allocator, &[_]u8{byte});
        defer std.testing.allocator.free(escaped);
        var expected_buffer: [6]u8 = undefined;
        const expected = switch (byte) {
            '\n' => "\\n",
            '\r' => "\\r",
            '\t' => "\\t",
            else => try std.fmt.bufPrint(&expected_buffer, "\\u00{x:0>2}", .{byte}),
        };
        try std.testing.expectEqualStrings(expected, escaped);
    }
}
