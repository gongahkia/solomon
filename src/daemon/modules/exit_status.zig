const std = @import("std");

pub fn render(allocator: std.mem.Allocator, exit_code: i32, show_zero: bool) !?[]u8 {
    if (exit_code == 0 and !show_zero) return null;
    return try std.fmt.allocPrint(allocator, "\x1b[31mexit:{d}\x1b[0m", .{exit_code});
}

test "hides zero exit code" {
    try std.testing.expect(try render(std.testing.allocator, 0, false) == null);
}

test "renders zero exit code when configured" {
    const rendered = (try render(std.testing.allocator, 0, true)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("\x1b[31mexit:0\x1b[0m", rendered);
}

test "renders nonzero exit code in red" {
    const rendered = (try render(std.testing.allocator, 2, false)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("\x1b[31mexit:2\x1b[0m", rendered);
}
