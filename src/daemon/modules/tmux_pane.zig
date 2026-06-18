const std = @import("std");

pub const Options = struct {
    enabled: bool = true,
};

pub fn render(allocator: std.mem.Allocator, tmux_pane: ?[]const u8, options: Options) !?[]u8 {
    if (!options.enabled) return null;
    const raw = tmux_pane orelse return null;
    const pane = std.mem.trim(u8, raw, " \t\r\n");
    if (pane.len == 0) return null;
    return try std.fmt.allocPrint(allocator, "tmux:{s}", .{pane});
}

test "hides outside tmux" {
    try std.testing.expect(try render(std.testing.allocator, null, .{}) == null);
    try std.testing.expect(try render(std.testing.allocator, "", .{}) == null);
}

test "renders tmux pane id" {
    const rendered = (try render(std.testing.allocator, "%3", .{})).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("tmux:%3", rendered);
}

test "disabled option hides pane" {
    try std.testing.expect(try render(std.testing.allocator, "%3", .{ .enabled = false }) == null);
}
