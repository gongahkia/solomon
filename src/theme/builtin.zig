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
    .{ .name = "okiya-day", .path = "themes/okiya-day.toml" },
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

test "built-in theme glyphs include ascii fallbacks" {
    for (themes) |theme| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, theme.path, 1024 * 1024);
        defer std.testing.allocator.free(source);
        try expectGlyphFallbacks(source);
    }
}

fn expectContains(source: []const u8, needle: []const u8) !void {
    try std.testing.expect(std.mem.indexOf(u8, source, needle) != null);
}

fn expectGlyphFallbacks(source: []const u8) !void {
    var in_segment = false;
    var glyph: []const u8 = "";
    var ascii: []const u8 = "";
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r\n");
        if (line.len == 0) continue;
        if (line[0] == '[') {
            if (in_segment and glyph.len > 0) try std.testing.expect(ascii.len > 0);
            in_segment = std.mem.startsWith(u8, line, "[segments.");
            glyph = "";
            ascii = "";
            continue;
        }
        if (!in_segment) continue;
        const split = std.mem.indexOfScalar(u8, line, '=') orelse continue;
        const key = std.mem.trim(u8, line[0..split], " \t\r\n");
        const value = unquote(std.mem.trim(u8, line[split + 1 ..], " \t\r\n"));
        if (std.mem.eql(u8, key, "glyph")) {
            glyph = value;
        } else if (std.mem.eql(u8, key, "ascii")) {
            ascii = value;
        }
    }
    if (in_segment and glyph.len > 0) try std.testing.expect(ascii.len > 0);
}

fn unquote(value: []const u8) []const u8 {
    if (value.len >= 2 and value[0] == '"' and value[value.len - 1] == '"') return value[1 .. value.len - 1];
    return value;
}
