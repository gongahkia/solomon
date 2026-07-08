const std = @import("std");
const contrast = @import("contrast.zig");
const loader = @import("loader.zig");

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

pub fn pathForId(id: []const u8) ?[]const u8 {
    for (themes) |theme| {
        if (std.mem.eql(u8, theme.name, id)) return theme.path;
    }
    return null;
}

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

test "built-in theme segments include a11y labels" {
    for (themes) |theme| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, theme.path, 1024 * 1024);
        defer std.testing.allocator.free(source);
        try expectA11yLabels(source);
    }
}

test "built-in themes render under glyph and color cap matrix" {
    const color_caps = [_]contrast.ColorCaps{ .none, .@"16", .@"256", .truecolor };
    const glyph_tiers = [_]loader.GlyphTier{ .ascii, .unicode, .nerdfont };

    for (themes) |asset| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, asset.path, 1024 * 1024);
        defer std.testing.allocator.free(source);

        var diagnostic: loader.Diagnostic = .{};
        var theme = try loader.parse(std.testing.allocator, source, &diagnostic);
        defer theme.deinit(std.testing.allocator);

        const failures = try loader.validateAlloc(std.testing.allocator, theme);
        defer std.testing.allocator.free(failures);
        try std.testing.expectEqual(@as(usize, 0), failures.len);

        for (color_caps) |color_cap| {
            for (glyph_tiers) |glyph_tier| {
                const rendered = try renderMatrixLineAlloc(std.testing.allocator, theme, color_cap, glyph_tier);
                defer std.testing.allocator.free(rendered);
                try std.testing.expect(rendered.len > 0);
                try std.testing.expect(std.mem.indexOf(u8, rendered, "~/work/shisa") != null);
                try std.testing.expect(std.mem.indexOf(u8, rendered, "main") != null);
            }
        }
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

fn expectA11yLabels(source: []const u8) !void {
    var in_segment = false;
    var a11y: []const u8 = "";
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r\n");
        if (line.len == 0) continue;
        if (line[0] == '[') {
            if (in_segment) try std.testing.expect(a11y.len > 0);
            in_segment = std.mem.startsWith(u8, line, "[segments.");
            a11y = "";
            continue;
        }
        if (!in_segment) continue;
        const split = std.mem.indexOfScalar(u8, line, '=') orelse continue;
        const key = std.mem.trim(u8, line[0..split], " \t\r\n");
        const value = unquote(std.mem.trim(u8, line[split + 1 ..], " \t\r\n"));
        if (std.mem.eql(u8, key, "a11y")) a11y = value;
    }
    if (in_segment) try std.testing.expect(a11y.len > 0);
}

fn unquote(value: []const u8) []const u8 {
    if (value.len >= 2 and value[0] == '"' and value[value.len - 1] == '"') return value[1 .. value.len - 1];
    return value;
}

fn renderMatrixLineAlloc(allocator: std.mem.Allocator, theme: loader.Theme, color_cap: contrast.ColorCaps, glyph_tier: loader.GlyphTier) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    for (theme.segments, 0..) |segment, index| {
        if (index > 0) try out.appendSlice(allocator, theme.separators.segment);
        var styled = false;
        styled = try appendSegmentColorSgr(allocator, &out, theme, segment.fg, .foreground, color_cap) or styled;
        styled = try appendSegmentColorSgr(allocator, &out, theme, segment.bg, .background, color_cap) or styled;
        try out.appendSlice(allocator, theme.separators.left);
        try out.appendSlice(allocator, segment.prefix);
        try out.appendSlice(allocator, loader.resolveSegmentGlyph(segment, glyph_tier));
        try out.appendSlice(allocator, previewValue(segment.id));
        try out.appendSlice(allocator, segment.suffix);
        try out.appendSlice(allocator, theme.separators.right);
        if (styled) try out.appendSlice(allocator, "\x1b[0m");
    }

    return out.toOwnedSlice(allocator);
}

fn appendSegmentColorSgr(
    allocator: std.mem.Allocator,
    out: *std.ArrayList(u8),
    theme: loader.Theme,
    ref: []const u8,
    role: contrast.ColorRole,
    color_cap: contrast.ColorCaps,
) !bool {
    if (ref.len == 0) return false;
    const rgb = loader.resolvePaletteColor(theme, ref) orelse return false;
    const sgr = try contrast.formatSgrColorAlloc(allocator, role, rgb, color_cap);
    defer allocator.free(sgr);
    if (sgr.len == 0) return false;
    try out.appendSlice(allocator, sgr);
    return true;
}

fn previewValue(id: []const u8) []const u8 {
    if (std.mem.eql(u8, id, "cwd")) return "~/work/shisa";
    if (std.mem.eql(u8, id, "git_branch")) return "main*";
    if (std.mem.eql(u8, id, "exit_status")) return "2";
    if (std.mem.eql(u8, id, "jobs")) return "2";
    if (std.mem.eql(u8, id, "cmd_duration")) return "1.5s";
    if (std.mem.eql(u8, id, "time")) return "14:32";
    if (std.mem.eql(u8, id, "language_versions")) return "zig:0.15";
    return id;
}
