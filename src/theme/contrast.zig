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

pub const ColorCaps = enum {
    truecolor,
    @"256",
    @"16",
    none,

    pub fn fromName(value: []const u8) ?ColorCaps {
        if (std.mem.eql(u8, value, "truecolor")) return .truecolor;
        if (std.mem.eql(u8, value, "256") or std.mem.eql(u8, value, "ansi256")) return .@"256";
        if (std.mem.eql(u8, value, "16") or std.mem.eql(u8, value, "ansi")) return .@"16";
        if (std.mem.eql(u8, value, "none")) return .none;
        return null;
    }
};

pub const ColorRole = enum {
    foreground,
    background,
};

pub const DowncastColor = union(enum) {
    truecolor: Rgb,
    ansi256: u8,
    ansi16: u8,
    none,
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
    if (parseOklabColor(trimmed)) |rgb| return rgb;
    if (parseOklchColor(trimmed)) |rgb| return rgb;
    return parseAnsiColor(trimmed);
}

pub fn validateThemeContrastAlloc(allocator: std.mem.Allocator, source: []const u8) ![]ContrastFailure {
    return validateThemeContrastWithThresholdsAlloc(allocator, source, 4.5, 3.0);
}

pub fn validateThemeContrastWithThresholdsAlloc(allocator: std.mem.Allocator, source: []const u8, text_required: f64, ui_required: f64) ![]ContrastFailure {
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
        if (ratio < text_required) {
            try failures.append(allocator, .{ .target = segment.id, .role = "text", .ratio = ratio, .required = text_required });
        }
    }

    inline for (.{ "accent", "success", "warning", "danger" }) |slot| {
        if (resolveThemeColor(palette.items, "@" ++ slot, 0)) |rgb| {
            const ratio = wcagContrastRatio(rgb, default_bg);
            if (ratio < ui_required) {
                try failures.append(allocator, .{ .target = slot, .role = "ui", .ratio = ratio, .required = ui_required });
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

pub fn oklabToRgb(color: Oklab) Rgb {
    const l_root = color.l + 0.3963377774 * color.a + 0.2158037573 * color.b;
    const m_root = color.l - 0.1055613458 * color.a - 0.0638541728 * color.b;
    const s_root = color.l - 0.0894841775 * color.a - 1.2914855480 * color.b;
    const l = l_root * l_root * l_root;
    const m = m_root * m_root * m_root;
    const s = s_root * s_root * s_root;
    return .{
        .r = linearSrgbToByte(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        .g = linearSrgbToByte(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        .b = linearSrgbToByte(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    };
}

pub fn downcastColor(rgb: Rgb, caps: ColorCaps) DowncastColor {
    return switch (caps) {
        .truecolor => .{ .truecolor = rgb },
        .@"256" => .{ .ansi256 = nearestAnsi256Index(rgb) },
        .@"16" => .{ .ansi16 = nearestAnsi16Index(rgb) },
        .none => .none,
    };
}

pub fn nearestAnsi256Index(rgb: Rgb) u8 {
    return nearestAnsiIndex(rgb, 256);
}

pub fn nearestAnsi16Index(rgb: Rgb) u8 {
    return nearestAnsiIndex(rgb, 16);
}

pub fn formatSgrColorAlloc(allocator: std.mem.Allocator, role: ColorRole, rgb: Rgb, caps: ColorCaps) ![]u8 {
    return switch (downcastColor(rgb, caps)) {
        .truecolor => |color| try std.fmt.allocPrint(
            allocator,
            "\x1b[{d};2;{d};{d};{d}m",
            .{ colorRoleTruecolorCode(role), color.r, color.g, color.b },
        ),
        .ansi256 => |index| try std.fmt.allocPrint(
            allocator,
            "\x1b[{d};5;{d}m",
            .{ colorRole256Code(role), index },
        ),
        .ansi16 => |index| try std.fmt.allocPrint(
            allocator,
            "\x1b[{d}m",
            .{ansi16SgrCode(role, index)},
        ),
        .none => try allocator.dupe(u8, ""),
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

fn parseOklabColor(value: []const u8) ?Rgb {
    const args = colorFunctionArgs(value, "oklab") orelse return null;
    var parts = splitColorArgs(args);
    const l = parseLightness(parts.next() orelse return null) orelse return null;
    const a = parseFiniteFloat(parts.next() orelse return null) orelse return null;
    const b = parseFiniteFloat(parts.next() orelse return null) orelse return null;
    if (parts.next() != null) return null;
    return oklabToRgb(.{ .l = l, .a = a, .b = b });
}

fn parseOklchColor(value: []const u8) ?Rgb {
    const args = colorFunctionArgs(value, "oklch") orelse return null;
    var parts = splitColorArgs(args);
    const l = parseLightness(parts.next() orelse return null) orelse return null;
    const chroma = parseFiniteFloat(parts.next() orelse return null) orelse return null;
    const hue_degrees = parseHueDegrees(parts.next() orelse return null) orelse return null;
    if (parts.next() != null) return null;
    const hue_radians = hue_degrees * std.math.pi / 180.0;
    return oklabToRgb(.{
        .l = l,
        .a = chroma * std.math.cos(hue_radians),
        .b = chroma * std.math.sin(hue_radians),
    });
}

fn colorFunctionArgs(value: []const u8, name: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, value, name)) return null;
    if (value.len < name.len + 2 or value[name.len] != '(' or value[value.len - 1] != ')') return null;
    return value[name.len + 1 .. value.len - 1];
}

fn splitColorArgs(args: []const u8) std.mem.TokenIterator(u8, .any) {
    return std.mem.tokenizeAny(u8, args, " \t\r\n,");
}

fn parseLightness(value: []const u8) ?f64 {
    if (std.mem.endsWith(u8, value, "%")) {
        const percent = parseFiniteFloat(value[0 .. value.len - 1]) orelse return null;
        return percent / 100.0;
    }
    return parseFiniteFloat(value);
}

fn parseHueDegrees(value: []const u8) ?f64 {
    if (std.mem.endsWith(u8, value, "deg")) return parseFiniteFloat(value[0 .. value.len - 3]);
    if (std.mem.endsWith(u8, value, "rad")) {
        const radians = parseFiniteFloat(value[0 .. value.len - 3]) orelse return null;
        return radians * 180.0 / std.math.pi;
    }
    if (std.mem.endsWith(u8, value, "turn")) {
        const turns = parseFiniteFloat(value[0 .. value.len - 4]) orelse return null;
        return turns * 360.0;
    }
    return parseFiniteFloat(value);
}

fn parseFiniteFloat(value: []const u8) ?f64 {
    const parsed = std.fmt.parseFloat(f64, value) catch return null;
    if (!std.math.isFinite(parsed)) return null;
    return parsed;
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
    return ansiIndexRgb(index);
}

pub fn ansiIndexRgb(index: u8) Rgb {
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

fn nearestAnsiIndex(rgb: Rgb, comptime limit: u16) u8 {
    var best_index: u8 = 0;
    var best_distance: u32 = std.math.maxInt(u32);
    var index: u16 = 0;
    while (index < limit) : (index += 1) {
        const candidate_index: u8 = @intCast(index);
        const distance = colorDistanceSquared(rgb, ansiIndexRgb(candidate_index));
        if (distance < best_distance) {
            best_index = candidate_index;
            best_distance = distance;
        }
    }
    return best_index;
}

fn colorDistanceSquared(a: Rgb, b: Rgb) u32 {
    return channelDistanceSquared(a.r, b.r) + channelDistanceSquared(a.g, b.g) + channelDistanceSquared(a.b, b.b);
}

fn channelDistanceSquared(a: u8, b: u8) u32 {
    const lhs: i32 = @intCast(a);
    const rhs: i32 = @intCast(b);
    const delta = lhs - rhs;
    return @intCast(delta * delta);
}

fn colorRoleTruecolorCode(role: ColorRole) u8 {
    return switch (role) {
        .foreground => 38,
        .background => 48,
    };
}

fn colorRole256Code(role: ColorRole) u8 {
    return colorRoleTruecolorCode(role);
}

fn ansi16SgrCode(role: ColorRole, index: u8) u8 {
    std.debug.assert(index < 16);
    return switch (role) {
        .foreground => if (index < 8) 30 + index else 90 + (index - 8),
        .background => if (index < 8) 40 + index else 100 + (index - 8),
    };
}

fn srgbByteToLinear(byte: u8) f64 {
    const value: f64 = @as(f64, @floatFromInt(byte)) / 255.0;
    if (value <= 0.04045) return value / 12.92;
    return std.math.pow(f64, (value + 0.055) / 1.055, 2.4);
}

fn linearSrgbToByte(value: f64) u8 {
    const srgb = if (value <= 0.0031308) 12.92 * value else 1.055 * std.math.pow(f64, value, 1.0 / 2.4) - 0.055;
    const clamped = @min(@max(srgb, 0.0), 1.0);
    return @intFromFloat(std.math.round(clamped * 255.0));
}

test "parses theme color values" {
    try std.testing.expectEqual(Rgb{ .r = 255, .g = 255, .b = 255 }, parseColor("#fff").?);
    try std.testing.expectEqual(Rgb{ .r = 51, .g = 102, .b = 255 }, parseColor("#3366ff").?);
    try std.testing.expectEqual(Rgb{ .r = 0, .g = 255, .b = 255 }, parseColor("14").?);
    try std.testing.expectEqual(Rgb{ .r = 175, .g = 135, .b = 0 }, parseColor("136").?);
    try std.testing.expectEqual(Rgb{ .r = 255, .g = 255, .b = 255 }, parseColor("oklab(1 0 0)").?);
    try std.testing.expectEqual(Rgb{ .r = 0, .g = 0, .b = 0 }, parseColor("oklch(0% 0 0deg)").?);
    try expectRgbApprox(Rgb{ .r = 255, .g = 0, .b = 0 }, parseColor("oklab(0.62796 0.22486 0.12585)").?, 1);
    try expectRgbApprox(Rgb{ .r = 255, .g = 0, .b = 0 }, parseColor("oklch(62.796% 0.25768 29.23deg)").?, 1);
}

test "matches established Oklab reference values" {
    try expectOklabApprox(.{ .l = 1.000000, .a = 0.000000, .b = 0.000000 }, rgbToOklab(.{ .r = 255, .g = 255, .b = 255 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.627955, .a = 0.224863, .b = 0.125846 }, rgbToOklab(.{ .r = 255, .g = 0, .b = 0 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.866440, .a = -0.233888, .b = 0.179498 }, rgbToOklab(.{ .r = 0, .g = 255, .b = 0 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.452014, .a = -0.032457, .b = -0.311528 }, rgbToOklab(.{ .r = 0, .g = 0, .b = 255 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.905399, .a = -0.149444, .b = -0.039398 }, rgbToOklab(.{ .r = 0, .g = 255, .b = 255 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.701674, .a = 0.274566, .b = -0.169156 }, rgbToOklab(.{ .r = 255, .g = 0, .b = 255 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.967983, .a = -0.071369, .b = 0.198570 }, rgbToOklab(.{ .r = 255, .g = 255, .b = 0 }), 0.000002);
    try expectOklabApprox(.{ .l = 0.000000, .a = 0.000000, .b = 0.000000 }, rgbToOklab(.{ .r = 0, .g = 0, .b = 0 }), 0.000002);
}

test "matches established Oklch reference values" {
    try expectRgbApprox(Rgb{ .r = 255, .g = 0, .b = 0 }, parseColor("oklch(0.627954 0.257627 29.2271)").?, 1);
    try expectRgbApprox(Rgb{ .r = 0, .g = 255, .b = 0 }, parseColor("oklch(0.866439 0.294803 142.5112)").?, 1);
    try expectRgbApprox(Rgb{ .r = 0, .g = 0, .b = 255 }, parseColor("oklch(0.452013 0.313319 264.058541)").?, 1);
}

fn expectOklabApprox(expected: Oklab, actual: Oklab, tolerance: f64) !void {
    try std.testing.expectApproxEqAbs(expected.l, actual.l, tolerance);
    try std.testing.expectApproxEqAbs(expected.a, actual.a, tolerance);
    try std.testing.expectApproxEqAbs(expected.b, actual.b, tolerance);
}

fn expectRgbApprox(expected: Rgb, actual: Rgb, tolerance: u8) !void {
    try std.testing.expect(absByteDiff(expected.r, actual.r) <= tolerance);
    try std.testing.expect(absByteDiff(expected.g, actual.g) <= tolerance);
    try std.testing.expect(absByteDiff(expected.b, actual.b) <= tolerance);
}

fn absByteDiff(a: u8, b: u8) u8 {
    return if (a > b) a - b else b - a;
}

test "downcasts colors to terminal capability tiers" {
    const red = Rgb{ .r = 255, .g = 0, .b = 0 };
    try std.testing.expectEqual(ColorCaps.truecolor, ColorCaps.fromName("truecolor").?);
    try std.testing.expectEqual(ColorCaps.@"256", ColorCaps.fromName("ansi256").?);
    try std.testing.expectEqual(ColorCaps.@"16", ColorCaps.fromName("ansi").?);
    try std.testing.expectEqual(ColorCaps.none, ColorCaps.fromName("none").?);
    try std.testing.expectEqual(@as(u8, 9), nearestAnsi256Index(red));
    try std.testing.expectEqual(@as(u8, 9), nearestAnsi16Index(red));
    try std.testing.expectEqual(@as(u8, 136), nearestAnsi256Index(Rgb{ .r = 175, .g = 135, .b = 0 }));
    try std.testing.expectEqual(@as(u8, 14), nearestAnsi16Index(Rgb{ .r = 0, .g = 255, .b = 255 }));
}

test "formats downcast colors as SGR" {
    const allocator = std.testing.allocator;
    const truecolor = try formatSgrColorAlloc(allocator, .foreground, Rgb{ .r = 51, .g = 102, .b = 255 }, .truecolor);
    defer allocator.free(truecolor);
    try std.testing.expectEqualStrings("\x1b[38;2;51;102;255m", truecolor);

    const ansi256 = try formatSgrColorAlloc(allocator, .background, Rgb{ .r = 175, .g = 135, .b = 0 }, .@"256");
    defer allocator.free(ansi256);
    try std.testing.expectEqualStrings("\x1b[48;5;136m", ansi256);

    const ansi16 = try formatSgrColorAlloc(allocator, .foreground, Rgb{ .r = 255, .g = 0, .b = 0 }, .@"16");
    defer allocator.free(ansi16);
    try std.testing.expectEqualStrings("\x1b[91m", ansi16);

    const none = try formatSgrColorAlloc(allocator, .foreground, Rgb{ .r = 255, .g = 0, .b = 0 }, .none);
    defer allocator.free(none);
    try std.testing.expectEqualStrings("", none);
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
