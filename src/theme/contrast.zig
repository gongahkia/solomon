const std = @import("std");

pub const Rgb = struct {
    r: u8,
    g: u8,
    b: u8,
};

pub const Oklab = struct {
    l: f64,
    a: f64,
    b: f64,
};

pub const ContrastFailure = struct {
    target: []const u8,
    role: []const u8,
    ratio: f64,
    required: f64,
};

const PaletteEntry = struct {
    name: []const u8,
    value: []const u8,
};

const SegmentStyle = struct {
    id: []const u8,
    fg: []const u8 = "",
    bg: []const u8 = "",
};

pub fn parseColor(value: []const u8) ?Rgb {
    const trimmed = std.mem.trim(u8, value, " \t\r\n\"");
    if (parseHexColor(trimmed)) |rgb| return rgb;
    return parseAnsiColor(trimmed);
}

pub fn validateThemeContrastAlloc(allocator: std.mem.Allocator, source: []const u8) ![]ContrastFailure {
    var palette: std.ArrayList(PaletteEntry) = .empty;
    defer palette.deinit(allocator);
    var segments: std.ArrayList(SegmentStyle) = .empty;
    defer segments.deinit(allocator);

    try parseThemeContrastSource(allocator, source, &palette, &segments);

    var failures: std.ArrayList(ContrastFailure) = .empty;
    const default_fg = resolveThemeColor(palette.items, "@fg", 0) orelse Rgb{ .r = 255, .g = 255, .b = 255 };
    const default_bg = Rgb{ .r = 0, .g = 0, .b = 0 };

    for (segments.items) |segment| {
        const fg = if (segment.fg.len > 0) resolveThemeColor(palette.items, segment.fg, 0) orelse default_fg else default_fg;
        const bg = if (segment.bg.len > 0) resolveThemeColor(palette.items, segment.bg, 0) orelse default_bg else default_bg;
        const ratio = wcagContrastRatio(fg, bg);
        if (ratio < 4.5) {
            try failures.append(allocator, .{ .target = segment.id, .role = "text", .ratio = ratio, .required = 4.5 });
        }
    }

    inline for (.{ "accent", "success", "warning", "danger" }) |slot| {
        if (resolveThemeColor(palette.items, "@" ++ slot, 0)) |rgb| {
            const ratio = wcagContrastRatio(rgb, default_bg);
            if (ratio < 3.0) {
                try failures.append(allocator, .{ .target = slot, .role = "ui", .ratio = ratio, .required = 3.0 });
            }
        }
    }

    return failures.toOwnedSlice(allocator);
}

pub fn formatContrastFailuresAlloc(allocator: std.mem.Allocator, failures: []const ContrastFailure) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    for (failures) |failure| {
        try std.fmt.format(
            out.writer(allocator),
            "theme contrast: {s} {s} ratio {d:.2}:1 below {d:.1}:1\n",
            .{ failure.target, failure.role, failure.ratio, failure.required },
        );
    }
    return out.toOwnedSlice(allocator);
}

pub fn oklabContrastDelta(fg: Rgb, bg: Rgb) f64 {
    return @abs(rgbToOklab(fg).l - rgbToOklab(bg).l);
}

pub fn wcagContrastRatio(fg: Rgb, bg: Rgb) f64 {
    const fg_luminance = relativeLuminance(fg);
    const bg_luminance = relativeLuminance(bg);
    const lighter = @max(fg_luminance, bg_luminance);
    const darker = @min(fg_luminance, bg_luminance);
    return (lighter + 0.05) / (darker + 0.05);
}

pub fn relativeLuminance(rgb: Rgb) f64 {
    const r = srgbByteToLinear(rgb.r);
    const g = srgbByteToLinear(rgb.g);
    const b = srgbByteToLinear(rgb.b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

pub fn rgbToOklab(rgb: Rgb) Oklab {
    const r = srgbByteToLinear(rgb.r);
    const g = srgbByteToLinear(rgb.g);
    const b = srgbByteToLinear(rgb.b);
    const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
    const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
    const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
    const l_root = std.math.pow(f64, l, 1.0 / 3.0);
    const m_root = std.math.pow(f64, m, 1.0 / 3.0);
    const s_root = std.math.pow(f64, s, 1.0 / 3.0);
    return .{
        .l = 0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
        .a = 1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
        .b = 0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
    };
}

fn parseThemeContrastSource(
    allocator: std.mem.Allocator,
    source: []const u8,
    palette: *std.ArrayList(PaletteEntry),
    segments: *std.ArrayList(SegmentStyle),
) !void {
    var section: enum { none, palette, segment } = .none;
    var current_segment: []const u8 = "";
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const comment_start = std.mem.indexOfScalar(u8, raw_line, '#') orelse raw_line.len;
        const line = std.mem.trim(u8, raw_line[0..comment_start], " \t\r\n");
        if (line.len == 0) continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            const body = line[1 .. line.len - 1];
            if (std.mem.eql(u8, body, "palette")) {
                section = .palette;
                current_segment = "";
            } else if (std.mem.startsWith(u8, body, "segments.")) {
                section = .segment;
                current_segment = body["segments.".len..];
                _ = try segmentStyle(allocator, segments, current_segment);
            } else {
                section = .none;
                current_segment = "";
            }
            continue;
        }
        const kv = keyValue(line) orelse continue;
        switch (section) {
            .palette => try palette.append(allocator, .{ .name = kv.key, .value = unquote(kv.value) }),
            .segment => {
                var style = try segmentStyle(allocator, segments, current_segment);
                if (std.mem.eql(u8, kv.key, "fg")) {
                    style.fg = unquote(kv.value);
                } else if (std.mem.eql(u8, kv.key, "bg")) {
                    style.bg = unquote(kv.value);
                }
            },
            .none => {},
        }
    }
}

fn segmentStyle(allocator: std.mem.Allocator, segments: *std.ArrayList(SegmentStyle), id: []const u8) !*SegmentStyle {
    for (segments.items) |*segment| {
        if (std.mem.eql(u8, segment.id, id)) return segment;
    }
    try segments.append(allocator, .{ .id = id });
    return &segments.items[segments.items.len - 1];
}

fn keyValue(line: []const u8) ?struct { key: []const u8, value: []const u8 } {
    const split = std.mem.indexOfScalar(u8, line, '=') orelse return null;
    return .{
        .key = std.mem.trim(u8, line[0..split], " \t\r\n"),
        .value = std.mem.trim(u8, line[split + 1 ..], " \t\r\n"),
    };
}

fn unquote(value: []const u8) []const u8 {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (trimmed.len >= 2 and trimmed[0] == '"' and trimmed[trimmed.len - 1] == '"') return trimmed[1 .. trimmed.len - 1];
    return trimmed;
}

fn resolveThemeColor(palette: []const PaletteEntry, value: []const u8, depth: u8) ?Rgb {
    if (depth > 8) return null;
    const trimmed = unquote(value);
    if (trimmed.len == 0) return null;
    if (trimmed[0] == '@') {
        const name = trimmed[1..];
        for (palette) |entry| {
            if (std.mem.eql(u8, entry.name, name)) return resolveThemeColor(palette, entry.value, depth + 1);
        }
        return null;
    }
    return parseColor(trimmed);
}

fn parseHexColor(value: []const u8) ?Rgb {
    if (value.len == 7 and value[0] == '#') {
        return .{
            .r = parseHexByte(value[1], value[2]) orelse return null,
            .g = parseHexByte(value[3], value[4]) orelse return null,
            .b = parseHexByte(value[5], value[6]) orelse return null,
        };
    }
    if (value.len == 4 and value[0] == '#') {
        const r = parseHexDigit(value[1]) orelse return null;
        const g = parseHexDigit(value[2]) orelse return null;
        const b = parseHexDigit(value[3]) orelse return null;
        return .{ .r = r * 17, .g = g * 17, .b = b * 17 };
    }
    return null;
}

fn parseHexByte(high: u8, low: u8) ?u8 {
    const high_value = parseHexDigit(high) orelse return null;
    const low_value = parseHexDigit(low) orelse return null;
    return high_value * 16 + low_value;
}

fn parseHexDigit(byte: u8) ?u8 {
    if (byte >= '0' and byte <= '9') return byte - '0';
    if (byte >= 'a' and byte <= 'f') return byte - 'a' + 10;
    if (byte >= 'A' and byte <= 'F') return byte - 'A' + 10;
    return null;
}

fn parseAnsiColor(value: []const u8) ?Rgb {
    const index = std.fmt.parseInt(u8, value, 10) catch return null;
    const base = [_]Rgb{
        .{ .r = 0, .g = 0, .b = 0 },
        .{ .r = 128, .g = 0, .b = 0 },
        .{ .r = 0, .g = 128, .b = 0 },
        .{ .r = 128, .g = 128, .b = 0 },
        .{ .r = 0, .g = 0, .b = 128 },
        .{ .r = 128, .g = 0, .b = 128 },
        .{ .r = 0, .g = 128, .b = 128 },
        .{ .r = 192, .g = 192, .b = 192 },
        .{ .r = 128, .g = 128, .b = 128 },
        .{ .r = 255, .g = 0, .b = 0 },
        .{ .r = 0, .g = 255, .b = 0 },
        .{ .r = 255, .g = 255, .b = 0 },
        .{ .r = 0, .g = 0, .b = 255 },
        .{ .r = 255, .g = 0, .b = 255 },
        .{ .r = 0, .g = 255, .b = 255 },
        .{ .r = 255, .g = 255, .b = 255 },
    };
    if (index < 16) return base[index];
    if (index <= 231) {
        const cube = index - 16;
        const steps = [_]u8{ 0, 95, 135, 175, 215, 255 };
        return .{
            .r = steps[cube / 36],
            .g = steps[(cube / 6) % 6],
            .b = steps[cube % 6],
        };
    }
    const gray: u8 = 8 + (index - 232) * 10;
    return .{ .r = gray, .g = gray, .b = gray };
}

fn srgbByteToLinear(byte: u8) f64 {
    const value: f64 = @as(f64, @floatFromInt(byte)) / 255.0;
    if (value <= 0.04045) return value / 12.92;
    return std.math.pow(f64, (value + 0.055) / 1.055, 2.4);
}

test "parses theme color values" {
    try std.testing.expectEqual(Rgb{ .r = 255, .g = 255, .b = 255 }, parseColor("#fff").?);
    try std.testing.expectEqual(Rgb{ .r = 51, .g = 102, .b = 255 }, parseColor("#3366ff").?);
    try std.testing.expectEqual(Rgb{ .r = 0, .g = 255, .b = 255 }, parseColor("14").?);
    try std.testing.expectEqual(Rgb{ .r = 175, .g = 135, .b = 0 }, parseColor("136").?);
}

test "calculates oklab contrast delta" {
    const black = Rgb{ .r = 0, .g = 0, .b = 0 };
    const white = Rgb{ .r = 255, .g = 255, .b = 255 };
    const gray = Rgb{ .r = 128, .g = 128, .b = 128 };
    try std.testing.expect(oklabContrastDelta(white, black) > oklabContrastDelta(gray, black));
    try std.testing.expectEqual(@as(f64, 0), oklabContrastDelta(gray, gray));
}

test "calculates WCAG contrast ratio" {
    const black = Rgb{ .r = 0, .g = 0, .b = 0 };
    const white = Rgb{ .r = 255, .g = 255, .b = 255 };
    try std.testing.expectApproxEqAbs(@as(f64, 21.0), wcagContrastRatio(white, black), 0.0001);
    try std.testing.expectApproxEqAbs(@as(f64, 1.0), wcagContrastRatio(white, white), 0.0001);
}

test "validates theme contrast" {
    const source =
        \\[palette]
        \\fg = "15"
        \\accent = "14"
        \\success = "10"
        \\warning = "11"
        \\danger = "9"
        \\
        \\[segments.cwd]
        \\fg = "@fg"
        \\bg = ""
    ;
    const failures = try validateThemeContrastAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(failures);
    try std.testing.expectEqual(@as(usize, 0), failures.len);
}

test "reports weak theme contrast" {
    const source =
        \\[palette]
        \\fg = "8"
        \\accent = "0"
        \\success = "0"
        \\warning = "0"
        \\danger = "0"
        \\
        \\[segments.cwd]
        \\fg = "@accent"
    ;
    const failures = try validateThemeContrastAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(failures);
    try std.testing.expect(failures.len >= 2);
}
