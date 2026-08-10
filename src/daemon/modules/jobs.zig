const std = @import("std");

pub fn render(allocator: std.mem.Allocator, count: u32, show_zero: bool) !?[]u8 {
    if (count == 0 and !show_zero) return null;
    return try std.fmt.allocPrint(allocator, "jobs:{d}", .{count});
}

test "hides zero jobs" {
    try std.testing.expect(try render(std.testing.allocator, 0, false) == null);
}

test "renders zero jobs when configured" {
    const rendered = (try render(std.testing.allocator, 0, true)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("jobs:0", rendered);
}

test "renders nonzero jobs" {
    const rendered = (try render(std.testing.allocator, 3, false)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("jobs:3", rendered);
}
