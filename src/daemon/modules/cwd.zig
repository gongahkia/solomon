const std = @import("std");
const unicode_width = @import("unicode_width.zig");

pub const Options = struct {
    truncate_to: u8 = 3,
    home_tilde: bool = true,
    max_width: u16 = 0,
};

pub fn render(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8, options: Options) ![]u8 {
    const display = try tildeAlloc(allocator, cwd, home, options.home_tilde);
    defer allocator.free(display);
    const segment_truncated = try truncateSegmentsAlloc(allocator, display, options.truncate_to);
    defer allocator.free(segment_truncated);
    return truncateWidthAlloc(allocator, segment_truncated, options.max_width);
}

fn tildeAlloc(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8, home_tilde: bool) ![]u8 {
    if (home_tilde) {
        if (home) |home_path| {
            if (std.mem.eql(u8, cwd, home_path)) {
                return allocator.dupe(u8, "~");
            }
            if (std.mem.startsWith(u8, cwd, home_path) and cwd.len > home_path.len and cwd[home_path.len] == '/') {
                return std.fmt.allocPrint(allocator, "~{s}", .{cwd[home_path.len..]});
            }
        }
    }
    return allocator.dupe(u8, cwd);
}

fn truncateSegmentsAlloc(allocator: std.mem.Allocator, value: []const u8, max_segments: usize) ![]u8 {
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

fn truncateWidthAlloc(allocator: std.mem.Allocator, value: []const u8, max_width: usize) ![]u8 {
    if (max_width == 0 or visibleWidth(value) <= max_width) return allocator.dupe(u8, value);
    if (max_width <= 3) return allocator.dupe(u8, "..."[0..max_width]);

    const limit = max_width - 3;
    var width: usize = 0;
    var keep_start = value.len;
    while (keep_start > 0) {
        const start = previousUtf8Start(value, keep_start);
        const scalar_width = scalarWidth(value[start..keep_start]);
        if (width + scalar_width > limit) break;
        width += scalar_width;
        keep_start = start;
    }
    return std.fmt.allocPrint(allocator, "...{s}", .{value[keep_start..]});
}

fn visibleWidth(value: []const u8) usize {
    var width: usize = 0;
    var index: usize = 0;
    while (index < value.len) {
        const len = std.unicode.utf8ByteSequenceLength(value[index]) catch 1;
        if (index + len > value.len) {
            width += 1;
            index += 1;
            continue;
        }
        width += scalarWidth(value[index .. index + len]);
        index += len;
    }
    return width;
}

fn previousUtf8Start(value: []const u8, end: usize) usize {
    var index = end - 1;
    while (index > 0 and (value[index] & 0b1100_0000) == 0b1000_0000) index -= 1;
    return index;
}

fn scalarWidth(bytes: []const u8) usize {
    const codepoint = std.unicode.utf8Decode(bytes) catch return 1;
    return unicode_width.codepointWidth(codepoint);
}

test "renders home as tilde" {
    const rendered = try render(std.testing.allocator, "/Users/a/project", "/Users/a", .{ .truncate_to = 0 });
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("~/project", rendered);
}

test "truncates to trailing segments" {
    const rendered = try render(std.testing.allocator, "/a/b/c/d", null, .{ .truncate_to = 2 });
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings(".../c/d", rendered);
}

test "truncates to display width without splitting wide utf8" {
    const rendered = try render(std.testing.allocator, "/tmp/alpha/\xe7\x95\x8c\xef\xbd\x81", null, .{ .truncate_to = 0, .max_width = 8 });
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings(".../\xe7\x95\x8c\xef\xbd\x81", rendered);
}
