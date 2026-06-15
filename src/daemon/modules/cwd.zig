const std = @import("std");

pub fn render(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8, max_segments: usize) ![]u8 {
    const display = try tildeAlloc(allocator, cwd, home);
    defer allocator.free(display);
    return truncateAlloc(allocator, display, max_segments);
}

fn tildeAlloc(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8) ![]u8 {
    if (home) |home_path| {
        if (std.mem.eql(u8, cwd, home_path)) {
            return allocator.dupe(u8, "~");
        }
        if (std.mem.startsWith(u8, cwd, home_path) and cwd.len > home_path.len and cwd[home_path.len] == '/') {
            return std.fmt.allocPrint(allocator, "~{s}", .{cwd[home_path.len..]});
        }
    }
    return allocator.dupe(u8, cwd);
}

fn truncateAlloc(allocator: std.mem.Allocator, value: []const u8, max_segments: usize) ![]u8 {
    if (max_segments == 0) return allocator.dupe(u8, value);

    var segments: usize = 0;
    var index = value.len;
    while (index > 0) {
        while (index > 0 and value[index - 1] == '/') index -= 1;
        if (index == 0) break;
        segments += 1;
        while (index > 0 and value[index - 1] != '/') index -= 1;
    }

    if (segments <= max_segments) return allocator.dupe(u8, value);

    var keep_index = value.len;
    var kept: usize = 0;
    while (keep_index > 0 and kept < max_segments) {
        while (keep_index > 0 and value[keep_index - 1] == '/') keep_index -= 1;
        while (keep_index > 0 and value[keep_index - 1] != '/') keep_index -= 1;
        kept += 1;
    }

    return std.fmt.allocPrint(allocator, "...{s}", .{value[keep_index - 1 ..]});
}

test "renders home as tilde" {
    const rendered = try render(std.testing.allocator, "/Users/a/project", "/Users/a", 0);
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("~/project", rendered);
}

test "truncates to trailing segments" {
    const rendered = try render(std.testing.allocator, "/a/b/c/d", null, 2);
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings(".../c/d", rendered);
}
