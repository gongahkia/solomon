const std = @import("std");

pub fn render(allocator: std.mem.Allocator, exit_code: i32) !?[]u8 {
    if (exit_code == 0) return null;
    return try std.fmt.allocPrint(allocator, "\x1b[31mexit:{d}\x1b[0m", .{exit_code});
}

test "hides zero exit code" {
    try std.testing.expect(try render(std.testing.allocator, 0) == null);
}

test "renders nonzero exit code in red" {
    const rendered = (try render(std.testing.allocator, 2)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("\x1b[31mexit:2\x1b[0m", rendered);
}
