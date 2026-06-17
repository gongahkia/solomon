const std = @import("std");
const contrast = @import("contrast.zig");

const ThemeAsset = struct {
    name: []const u8,
    path: []const u8,
};

const themes = [_]ThemeAsset{
    .{ .name = "plain", .path = "themes/plain.toml" },
    .{ .name = "minimal-monochrome", .path = "themes/minimal-monochrome.toml" },
    .{ .name = "okiya-night", .path = "themes/okiya-night.toml" },
    .{ .name = "nord-dark", .path = "themes/nord-dark.toml" },
    .{ .name = "gruvbox-rainbow", .path = "themes/gruvbox-rainbow.toml" },
    .{ .name = "tokyo-night", .path = "themes/tokyo-night.toml" },
    .{ .name = "pure", .path = "themes/pure.toml" },
    .{ .name = "a11y", .path = "themes/a11y.toml" },
};

test "built-in themes include required schema fields" {
    for (themes) |theme| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, theme.path, 1024 * 1024);
        defer std.testing.allocator.free(source);

        try expectContains(source, "version = 1");

        const name_line = try std.fmt.allocPrint(std.testing.allocator, "name = \"{s}\"", .{theme.name});
        defer std.testing.allocator.free(name_line);
        try expectContains(source, name_line);

        inline for (.{ "[capabilities]", "[palette]", "[separators]", "[segments.cwd]", "[segments.git_branch]", "[segments.exit_status]", "[segments.jobs]", "[segments.cmd_duration]" }) |needle| {
            try expectContains(source, needle);
        }

        inline for (.{ "fg =", "muted =", "accent =", "success =", "warning =", "danger =" }) |needle| {
            try expectContains(source, needle);
        }
    }
}

test "a11y theme passes AAA contrast with ASCII glyphs" {
    const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, "themes/a11y.toml", 1024 * 1024);
    defer std.testing.allocator.free(source);
    try expectContains(source, "color = \"none\"");
    try expectContains(source, "glyphs = \"ascii\"");
    const failures = try contrast.validateThemeContrastWithThresholdsAlloc(std.testing.allocator, source, 7.0, 4.5);
    defer std.testing.allocator.free(failures);
    try std.testing.expectEqual(@as(usize, 0), failures.len);
}

fn expectContains(source: []const u8, needle: []const u8) !void {
    try std.testing.expect(std.mem.indexOf(u8, source, needle) != null);
}
