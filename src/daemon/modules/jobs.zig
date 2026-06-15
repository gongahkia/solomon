const std = @import("std");

pub fn render(allocator: std.mem.Allocator, count: u32) !?[]u8 {
    if (count == 0) return null;
    return try std.fmt.allocPrint(allocator, "jobs:{d}", .{count});
}

test "hides zero jobs" {
    try std.testing.expect(try render(std.testing.allocator, 0) == null);
}

test "renders nonzero jobs" {
    const rendered = (try render(std.testing.allocator, 3)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("jobs:3", rendered);
}
