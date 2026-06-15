const std = @import("std");

pub fn render(allocator: std.mem.Allocator, duration_ms: u64, threshold_ms: u64) !?[]u8 {
    if (duration_ms < threshold_ms) return null;
    if (duration_ms < 1000) {
        return try std.fmt.allocPrint(allocator, "took:{d}ms", .{duration_ms});
    }
    const seconds = duration_ms / 1000;
    const tenths = (duration_ms % 1000) / 100;
    return try std.fmt.allocPrint(allocator, "took:{d}.{d}s", .{ seconds, tenths });
}

test "hides duration below threshold" {
    try std.testing.expect(try render(std.testing.allocator, 999, 1000) == null);
}

test "renders duration above threshold" {
    const rendered = (try render(std.testing.allocator, 1234, 1000)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("took:1.2s", rendered);
}
