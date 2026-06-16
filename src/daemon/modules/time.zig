const std = @import("std");

pub fn render(allocator: std.mem.Allocator, enabled: bool, timestamp: i64) !?[]u8 {
    if (!enabled or timestamp < 0) return null;

    const day_seconds = (std.time.epoch.EpochSeconds{ .secs = @intCast(timestamp) }).getDaySeconds();
    const hour: u8 = @intCast(day_seconds.getHoursIntoDay());
    const minute: u8 = @intCast(day_seconds.getMinutesIntoHour());

    return try std.fmt.allocPrint(allocator, "time:{d}{d}:{d}{d}", .{ hour / 10, hour % 10, minute / 10, minute % 10 });
}

test "hides disabled time" {
    try std.testing.expect(try render(std.testing.allocator, false, 3660) == null);
}

test "renders utc hour and minute" {
    const rendered = (try render(std.testing.allocator, true, 3660)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("time:01:01", rendered);
}
