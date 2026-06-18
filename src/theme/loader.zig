const std = @import("std");
const contrast = @import("contrast.zig");

pub const Rgb = contrast.Rgb;

pub const Diagnostic = struct {
    message: []const u8 = "",
    line: usize = 0,
    column: usize = 0,
};

pub const ColorCapability = enum {
    none,
    ansi,
    ansi256,
    truecolor,
};

pub const GlyphCapability = enum {
    ascii,
    nerd_font,
};

pub const Capabilities = struct {
    color: ColorCapability = .ansi,
    glyphs: GlyphCapability = .ascii,
};

pub const PaletteEntry = struct {
    name: []u8,
    value: []u8,
};

pub const Separators = struct {
    segment: []u8,
    left: []u8,
    right: []u8,

    pub fn deinit(self: *Separators, allocator: std.mem.Allocator) void {
        allocator.free(self.segment);
        allocator.free(self.left);
        allocator.free(self.right);
        self.* = undefined;
    }
};

pub const Segment = struct {
    id: []u8,
    fg: []u8 = "",
    bg: []u8 = "",
    style: []u8 = "",
    glyph: []u8 = "",
    ascii: []u8 = "",
    prefix: []u8 = "",
    suffix: []u8 = "",
};

pub const Theme = struct {
    version: u32,
    name: []u8,
    extends: []u8,
    capabilities: Capabilities = .{},
    palette: []PaletteEntry,
    separators: Separators,
    segments: []Segment,

    pub fn deinit(self: *Theme, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.extends);
        freePalette(allocator, self.palette);
        var separators = self.separators;
        separators.deinit(allocator);
        freeSegments(allocator, self.segments);
        self.* = undefined;
    }
};

pub const ValidationFailure = struct {
    section: []const u8,
    key: []const u8,
    message: []const u8,
};

const Table = union(enum) {
    root,
    capabilities,
    palette,
    separators,
    segment: []const u8,
};

const Seen = struct {
    version: bool = false,
    name: bool = false,
    extends: bool = false,
    color: bool = false,
    glyphs: bool = false,
};

const SeparatorBuilder = struct {
    segment: ?[]u8 = null,
    left: ?[]u8 = null,
    right: ?[]u8 = null,
    seen_segment: bool = false,
    seen_left: bool = false,
    seen_right: bool = false,

    fn deinit(self: *SeparatorBuilder, allocator: std.mem.Allocator) void {
        if (self.segment) |value| allocator.free(value);
        if (self.left) |value| allocator.free(value);
        if (self.right) |value| allocator.free(value);
        self.* = .{};
    }

    fn finish(self: *SeparatorBuilder, allocator: std.mem.Allocator) !Separators {
        const segment_separator = if (self.segment) |value| value else try allocator.dupe(u8, " ");
        self.segment = null;
        errdefer allocator.free(segment_separator);
        const left = if (self.left) |value| value else try allocator.dupe(u8, "");
        self.left = null;
        errdefer allocator.free(left);
        const right = if (self.right) |value| value else try allocator.dupe(u8, "");
        self.right = null;
        return .{ .segment = segment_separator, .left = left, .right = right };
    }
};

const Trimmed = struct {
    text: []const u8,
    column: usize,
};

pub fn parse(allocator: std.mem.Allocator, source: []const u8, diagnostic: *Diagnostic) !Theme {
    diagnostic.* = .{};
    var parser = Parser{
        .allocator = allocator,
        .source = source,
        .diagnostic = diagnostic,
    };
    errdefer parser.deinitWorking();
    return parser.parse();
}

pub fn resolvePaletteSlot(theme: Theme, name: []const u8) ?Rgb {
    return resolvePaletteSlotDepth(theme, name, 0);
}

pub fn resolvePaletteColor(theme: Theme, value: []const u8) ?Rgb {
    return resolvePaletteColorDepth(theme, value, 0);
}

pub fn validateAlloc(allocator: std.mem.Allocator, theme: Theme) ![]ValidationFailure {
    var failures: std.ArrayList(ValidationFailure) = .empty;
    errdefer failures.deinit(allocator);

    if (!validThemeName(theme.name)) {
        try failures.append(allocator, .{ .section = "theme", .key = "name", .message = "invalid theme name" });
    }

    inline for (.{ "fg", "muted", "accent", "success", "warning", "danger" }) |slot| {
        if (resolvePaletteSlot(theme, slot) == null) {
            try failures.append(allocator, .{ .section = "palette", .key = slot, .message = "missing or invalid required slot" });
        }
    }

    for (theme.palette) |entry| {
        if (resolvePaletteColor(theme, entry.value) == null) {
            try failures.append(allocator, .{ .section = "palette", .key = entry.name, .message = "invalid color" });
        }
        if (!isRequiredPaletteSlot(entry.name) and !paletteSlotReferenced(theme, entry.name)) {
            try failures.append(allocator, .{ .section = "palette", .key = entry.name, .message = "unused custom slot" });
        }
    }

    inline for (.{ "cwd", "git_branch", "exit_status", "jobs", "cmd_duration" }) |id| {
        if (findSegment(theme, id) == null) {
            try failures.append(allocator, .{ .section = "segments", .key = id, .message = "missing required segment" });
        }
    }

    for (theme.segments) |item| {
        if (item.fg.len > 0 and resolvePaletteColor(theme, item.fg) == null) {
            try failures.append(allocator, .{ .section = item.id, .key = "fg", .message = "invalid color" });
        }
        if (item.bg.len > 0 and resolvePaletteColor(theme, item.bg) == null) {
            try failures.append(allocator, .{ .section = item.id, .key = "bg", .message = "invalid color" });
        }
        if (!validStyleList(item.style)) {
            try failures.append(allocator, .{ .section = item.id, .key = "style", .message = "invalid style" });
        }
        if (!isAscii(item.glyph) and item.ascii.len == 0) {
            try failures.append(allocator, .{ .section = item.id, .key = "ascii", .message = "missing ASCII fallback" });
        }
    }

    return failures.toOwnedSlice(allocator);
}

pub fn formatValidationFailuresAlloc(allocator: std.mem.Allocator, failures: []const ValidationFailure) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    for (failures) |failure| {
        try std.fmt.format(out.writer(allocator), "theme validate: {s}.{s}: {s}\n", .{ failure.section, failure.key, failure.message });
    }
    return out.toOwnedSlice(allocator);
}

const Parser = struct {
    allocator: std.mem.Allocator,
    source: []const u8,
    diagnostic: *Diagnostic,
    table: Table = .root,
    seen: Seen = .{},
    name: ?[]u8 = null,
    extends: ?[]u8 = null,
    capabilities: Capabilities = .{},
    separators: SeparatorBuilder = .{},
    palette: std.ArrayList(PaletteEntry) = .empty,
    segments: std.ArrayList(Segment) = .empty,

    fn parse(self: *Parser) !Theme {
        var offset: usize = 0;
        var line_no: usize = 1;
        while (offset <= self.source.len) : (line_no += 1) {
            const rest = self.source[offset..];
            const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
            var line = rest[0..line_len];
            if (line.len > 0 and line[line.len - 1] == '\r') line = line[0 .. line.len - 1];
            try self.parseLine(line_no, line);
            offset += line_len + 1;
            if (offset > self.source.len) break;
        }

        if (!self.seen.version) return self.fail(1, 1, "missing version");
        if (!self.seen.name) return self.fail(1, 1, "missing name");

        const name = self.name.?;
        self.name = null;
        errdefer self.allocator.free(name);
        const extends = if (self.extends) |value| value else try self.allocator.dupe(u8, "");
        self.extends = null;
        errdefer self.allocator.free(extends);
        const separators = try self.separators.finish(self.allocator);
        errdefer {
            var cleanup = separators;
            cleanup.deinit(self.allocator);
        }
        const palette = try self.palette.toOwnedSlice(self.allocator);
        errdefer freePalette(self.allocator, palette);
        const segments = try self.segments.toOwnedSlice(self.allocator);
        errdefer freeSegments(self.allocator, segments);

        return .{
            .version = 1,
            .name = name,
            .extends = extends,
            .capabilities = self.capabilities,
            .palette = palette,
            .separators = separators,
            .segments = segments,
        };
    }

    fn deinitWorking(self: *Parser) void {
        if (self.name) |value| self.allocator.free(value);
        if (self.extends) |value| self.allocator.free(value);
        self.separators.deinit(self.allocator);
        for (self.palette.items) |entry| {
            self.allocator.free(entry.name);
            self.allocator.free(entry.value);
        }
        self.palette.deinit(self.allocator);
        for (self.segments.items) |item| {
            freeSegment(self.allocator, item);
        }
        self.segments.deinit(self.allocator);
    }

    fn parseLine(self: *Parser, line_no: usize, line: []const u8) !void {
        const no_comment = stripComment(line);
        const trimmed = trimWithColumn(no_comment, 1);
        if (trimmed.text.len == 0) return;

        if (trimmed.text[0] == '[') {
            try self.parseTable(line_no, trimmed);
            return;
        }

        try self.parseKeyValue(line_no, trimmed);
    }

    fn parseTable(self: *Parser, line_no: usize, trimmed: Trimmed) !void {
        if (trimmed.text.len < 3 or trimmed.text[trimmed.text.len - 1] != ']') {
            return self.fail(line_no, trimmed.column, "invalid table header");
        }

        const inner = trimWithColumn(trimmed.text[1 .. trimmed.text.len - 1], trimmed.column + 1);
        if (inner.text.len == 0) return self.fail(line_no, inner.column, "empty table name");
        self.table = parseTableName(inner.text) orelse return self.fail(line_no, inner.column, "unknown table");
    }

    fn parseKeyValue(self: *Parser, line_no: usize, trimmed: Trimmed) !void {
        const eq_index = findEquals(trimmed.text) orelse return self.fail(line_no, trimmed.column, "expected key-value pair");
        const key = trimWithColumn(trimmed.text[0..eq_index], trimmed.column);
        const value = trimWithColumn(trimmed.text[eq_index + 1 ..], trimmed.column + eq_index + 1);
        if (key.text.len == 0) return self.fail(line_no, key.column, "empty key");
        if (value.text.len == 0) return self.fail(line_no, value.column, "empty value");

        switch (self.table) {
            .root => try self.parseRootKey(line_no, key, value),
            .capabilities => try self.parseCapabilitiesKey(line_no, key, value),
            .palette => try self.parsePaletteKey(line_no, key, value),
            .separators => try self.parseSeparatorsKey(line_no, key, value),
            .segment => |segment_id| try self.parseSegmentKey(line_no, segment_id, key, value),
        }
    }

    fn parseRootKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "version")) {
            try self.markUnseen(&self.seen.version, line_no, key.column);
            const parsed = try self.parseIntRange(value, line_no, 1, 1);
            _ = parsed;
        } else if (std.mem.eql(u8, key.text, "name")) {
            try self.markUnseen(&self.seen.name, line_no, key.column);
            self.name = try self.parseStringAlloc(value, line_no);
        } else if (std.mem.eql(u8, key.text, "extends")) {
            try self.markUnseen(&self.seen.extends, line_no, key.column);
            self.extends = try self.parseStringAlloc(value, line_no);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseCapabilitiesKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        const raw = try self.parseStringAlloc(value, line_no);
        defer self.allocator.free(raw);
        if (std.mem.eql(u8, key.text, "color")) {
            try self.markUnseen(&self.seen.color, line_no, key.column);
            self.capabilities.color = parseColorCapability(raw) orelse return self.fail(line_no, value.column, "invalid color capability");
        } else if (std.mem.eql(u8, key.text, "glyphs")) {
            try self.markUnseen(&self.seen.glyphs, line_no, key.column);
            self.capabilities.glyphs = parseGlyphCapability(raw) orelse return self.fail(line_no, value.column, "invalid glyph capability");
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parsePaletteKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        for (self.palette.items) |entry| {
            if (std.mem.eql(u8, entry.name, key.text)) return self.fail(line_no, key.column, "duplicate key");
        }
        const name = try self.allocator.dupe(u8, key.text);
        errdefer self.allocator.free(name);
        const color = try self.parseStringAlloc(value, line_no);
        errdefer self.allocator.free(color);
        try self.palette.append(self.allocator, .{ .name = name, .value = color });
    }

    fn parseSeparatorsKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "segment")) {
            try self.setSeparator(&self.separators.segment, &self.separators.seen_segment, line_no, key.column, value);
        } else if (std.mem.eql(u8, key.text, "left")) {
            try self.setSeparator(&self.separators.left, &self.separators.seen_left, line_no, key.column, value);
        } else if (std.mem.eql(u8, key.text, "right")) {
            try self.setSeparator(&self.separators.right, &self.separators.seen_right, line_no, key.column, value);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseSegmentKey(self: *Parser, line_no: usize, segment_id: []const u8, key: Trimmed, value: Trimmed) !void {
        var current_segment = try self.segmentForId(segment_id);
        if (std.mem.eql(u8, key.text, "fg")) {
            try self.setSegmentString(&current_segment.fg, line_no, value);
        } else if (std.mem.eql(u8, key.text, "bg")) {
            try self.setSegmentString(&current_segment.bg, line_no, value);
        } else if (std.mem.eql(u8, key.text, "style")) {
            try self.setSegmentString(&current_segment.style, line_no, value);
        } else if (std.mem.eql(u8, key.text, "glyph")) {
            try self.setSegmentString(&current_segment.glyph, line_no, value);
        } else if (std.mem.eql(u8, key.text, "ascii")) {
            try self.setSegmentString(&current_segment.ascii, line_no, value);
        } else if (std.mem.eql(u8, key.text, "prefix")) {
            try self.setSegmentString(&current_segment.prefix, line_no, value);
        } else if (std.mem.eql(u8, key.text, "suffix")) {
            try self.setSegmentString(&current_segment.suffix, line_no, value);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn setSeparator(self: *Parser, target: *?[]u8, seen: *bool, line_no: usize, column: usize, value: Trimmed) !void {
        try self.markUnseen(seen, line_no, column);
        target.* = try self.parseStringAlloc(value, line_no);
    }

    fn setSegmentString(self: *Parser, target: *[]u8, line_no: usize, value: Trimmed) !void {
        if (target.*.len != 0) return self.fail(line_no, value.column, "duplicate key");
        const parsed = try self.parseStringAlloc(value, line_no);
        self.allocator.free(target.*);
        target.* = parsed;
    }

    fn segmentForId(self: *Parser, id: []const u8) !*Segment {
        for (self.segments.items) |*item| {
            if (std.mem.eql(u8, item.id, id)) return item;
        }
        const new_segment = try self.emptySegment(id);
        errdefer freeSegment(self.allocator, new_segment);
        try self.segments.append(self.allocator, new_segment);
        return &self.segments.items[self.segments.items.len - 1];
    }

    fn emptySegment(self: *Parser, id: []const u8) !Segment {
        const owned_id = try self.allocator.dupe(u8, id);
        errdefer self.allocator.free(owned_id);
        const fg = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(fg);
        const bg = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(bg);
        const style = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(style);
        const glyph = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(glyph);
        const ascii = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(ascii);
        const prefix = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(prefix);
        const suffix = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(suffix);
        return .{
            .id = owned_id,
            .fg = fg,
            .bg = bg,
            .style = style,
            .glyph = glyph,
            .ascii = ascii,
            .prefix = prefix,
            .suffix = suffix,
        };
    }

    fn parseStringAlloc(self: *Parser, value: Trimmed, line_no: usize) ![]u8 {
        if (value.text.len < 2 or value.text[0] != '"' or value.text[value.text.len - 1] != '"') {
            return self.fail(line_no, value.column, "expected string");
        }

        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(self.allocator);

        var index: usize = 1;
        while (index < value.text.len - 1) : (index += 1) {
            const byte = value.text[index];
            if (byte == '\\') {
                index += 1;
                if (index >= value.text.len - 1) return self.fail(line_no, value.column + index, "invalid escape");
                switch (value.text[index]) {
                    '"' => try out.append(self.allocator, '"'),
                    '\\' => try out.append(self.allocator, '\\'),
                    'n' => try out.append(self.allocator, '\n'),
                    'r' => try out.append(self.allocator, '\r'),
                    't' => try out.append(self.allocator, '\t'),
                    else => return self.fail(line_no, value.column + index, "invalid escape"),
                }
            } else {
                try out.append(self.allocator, byte);
            }
        }

        return out.toOwnedSlice(self.allocator);
    }

    fn parseIntRange(self: *Parser, value: Trimmed, line_no: usize, min: i64, max: i64) !i64 {
        const parsed = std.fmt.parseInt(i64, value.text, 10) catch return self.fail(line_no, value.column, "expected integer");
        if (parsed < min or parsed > max) return self.fail(line_no, value.column, "integer out of range");
        return parsed;
    }

    fn markUnseen(self: *Parser, seen: *bool, line_no: usize, column: usize) !void {
        if (seen.*) return self.fail(line_no, column, "duplicate key");
        seen.* = true;
    }

    fn fail(self: *Parser, line_no: usize, column: usize, message: []const u8) error{InvalidTheme} {
        self.diagnostic.* = .{
            .message = message,
            .line = line_no,
            .column = column,
        };
        return error.InvalidTheme;
    }
};

fn parseTableName(name: []const u8) ?Table {
    if (std.mem.eql(u8, name, "capabilities")) return .capabilities;
    if (std.mem.eql(u8, name, "palette")) return .palette;
    if (std.mem.eql(u8, name, "separators")) return .separators;
    if (std.mem.startsWith(u8, name, "segments.")) {
        const segment_id = name["segments.".len..];
        if (segment_id.len == 0) return null;
        return .{ .segment = segment_id };
    }
    return null;
}

fn parseColorCapability(value: []const u8) ?ColorCapability {
    if (std.mem.eql(u8, value, "none")) return .none;
    if (std.mem.eql(u8, value, "ansi")) return .ansi;
    if (std.mem.eql(u8, value, "ansi256")) return .ansi256;
    if (std.mem.eql(u8, value, "truecolor")) return .truecolor;
    return null;
}

fn parseGlyphCapability(value: []const u8) ?GlyphCapability {
    if (std.mem.eql(u8, value, "ascii")) return .ascii;
    if (std.mem.eql(u8, value, "nerd-font")) return .nerd_font;
    return null;
}

fn resolvePaletteSlotDepth(theme: Theme, name: []const u8, depth: u8) ?Rgb {
    if (depth > 16) return null;
    for (theme.palette) |entry| {
        if (std.mem.eql(u8, entry.name, name)) {
            return resolvePaletteColorDepth(theme, entry.value, depth + 1);
        }
    }
    return null;
}

fn resolvePaletteColorDepth(theme: Theme, value: []const u8, depth: u8) ?Rgb {
    const trimmed = std.mem.trim(u8, value, " \t\r\n\"");
    if (trimmed.len == 0) return null;
    if (trimmed[0] == '@') return resolvePaletteSlotDepth(theme, trimmed[1..], depth + 1);
    return contrast.parseColor(trimmed);
}

fn validThemeName(name: []const u8) bool {
    if (name.len == 0) return false;
    if (!isLowerAlnum(name[0])) return false;
    for (name[1..]) |byte| {
        if (!isLowerAlnum(byte) and byte != '_' and byte != '-') return false;
    }
    return true;
}

fn isLowerAlnum(byte: u8) bool {
    return (byte >= 'a' and byte <= 'z') or (byte >= '0' and byte <= '9');
}

fn isRequiredPaletteSlot(name: []const u8) bool {
    inline for (.{ "fg", "muted", "accent", "success", "warning", "danger" }) |slot| {
        if (std.mem.eql(u8, name, slot)) return true;
    }
    return false;
}

fn paletteSlotReferenced(theme: Theme, name: []const u8) bool {
    for (theme.palette) |entry| {
        if (referencesPaletteSlot(entry.value, name)) return true;
    }
    for (theme.segments) |item| {
        if (referencesPaletteSlot(item.fg, name) or referencesPaletteSlot(item.bg, name)) return true;
    }
    return false;
}

fn referencesPaletteSlot(value: []const u8, name: []const u8) bool {
    if (value.len < 2 or value[0] != '@') return false;
    return std.mem.eql(u8, value[1..], name);
}

fn validStyleList(value: []const u8) bool {
    var parts = std.mem.tokenizeAny(u8, value, " \t\r\n");
    while (parts.next()) |part| {
        if (!validStyle(part)) return false;
    }
    return true;
}

fn validStyle(value: []const u8) bool {
    return std.mem.eql(u8, value, "bold") or
        std.mem.eql(u8, value, "dim") or
        std.mem.eql(u8, value, "italic") or
        std.mem.eql(u8, value, "underline");
}

fn isAscii(value: []const u8) bool {
    for (value) |byte| {
        if (byte > 0x7f) return false;
    }
    return true;
}

fn stripComment(line: []const u8) []const u8 {
    var in_string = false;
    var escaped = false;
    for (line, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '#' and !in_string) return line[0..index];
    }
    return line;
}

fn trimWithColumn(value: []const u8, base_column: usize) Trimmed {
    var start: usize = 0;
    var end: usize = value.len;
    while (start < end and isSpace(value[start])) : (start += 1) {}
    while (end > start and isSpace(value[end - 1])) : (end -= 1) {}
    return .{
        .text = value[start..end],
        .column = base_column + start,
    };
}

fn findEquals(value: []const u8) ?usize {
    var in_string = false;
    var escaped = false;
    for (value, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '=' and !in_string) return index;
    }
    return null;
}

fn isSpace(byte: u8) bool {
    return byte == ' ' or byte == '\t' or byte == '\r' or byte == '\n';
}

fn freePalette(allocator: std.mem.Allocator, palette: []PaletteEntry) void {
    for (palette) |entry| {
        allocator.free(entry.name);
        allocator.free(entry.value);
    }
    allocator.free(palette);
}

fn freeSegments(allocator: std.mem.Allocator, segments: []Segment) void {
    for (segments) |item| {
        freeSegment(allocator, item);
    }
    allocator.free(segments);
}

fn freeSegment(allocator: std.mem.Allocator, item: Segment) void {
    allocator.free(item.id);
    allocator.free(item.fg);
    allocator.free(item.bg);
    allocator.free(item.style);
    allocator.free(item.glyph);
    allocator.free(item.ascii);
    allocator.free(item.prefix);
    allocator.free(item.suffix);
}

fn paletteValue(theme: Theme, name: []const u8) ?[]const u8 {
    for (theme.palette) |entry| {
        if (std.mem.eql(u8, entry.name, name)) return entry.value;
    }
    return null;
}

fn findSegment(theme: Theme, id: []const u8) ?Segment {
    for (theme.segments) |item| {
        if (std.mem.eql(u8, item.id, id)) return item;
    }
    return null;
}

test "parses okiya-night theme" {
    const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, "themes/okiya-night.toml", 1024 * 1024);
    defer std.testing.allocator.free(source);

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(u32, 1), theme.version);
    try std.testing.expectEqualStrings("okiya-night", theme.name);
    try std.testing.expectEqualStrings("plain", theme.extends);
    try std.testing.expectEqual(ColorCapability.ansi256, theme.capabilities.color);
    try std.testing.expectEqual(GlyphCapability.ascii, theme.capabilities.glyphs);
    try std.testing.expectEqualStrings("209", paletteValue(theme, "accent").?);
    try std.testing.expectEqualStrings(" ", theme.separators.segment);
    const cwd = findSegment(theme, "cwd").?;
    try std.testing.expectEqualStrings("@accent", cwd.fg);
    try std.testing.expectEqualStrings("bold", cwd.style);
}

test "parses all built-in theme files" {
    const paths = [_][]const u8{
        "themes/plain.toml",
        "themes/minimal-monochrome.toml",
        "themes/okiya-night.toml",
        "themes/okiya-day.toml",
        "themes/nord-dark.toml",
        "themes/gruvbox-rainbow.toml",
        "themes/tokyo-night.toml",
        "themes/pure.toml",
        "themes/a11y.toml",
    };

    for (paths) |path| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 1024 * 1024);
        defer std.testing.allocator.free(source);
        var diagnostic: Diagnostic = .{};
        var theme = try parse(std.testing.allocator, source, &diagnostic);
        defer theme.deinit(std.testing.allocator);
        try std.testing.expect(theme.name.len > 0);
        try std.testing.expect(theme.palette.len >= 6);
        try std.testing.expect(findSegment(theme, "cwd") != null);
    }
}

test "resolves palette references" {
    const source =
        \\version = 1
        \\name = "refs"
        \\
        \\[palette]
        \\fg = "15"
        \\accent = "@fg"
        \\danger = "#ff0000"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(Rgb{ .r = 255, .g = 255, .b = 255 }, resolvePaletteSlot(theme, "accent").?);
    try std.testing.expectEqual(Rgb{ .r = 255, .g = 0, .b = 0 }, resolvePaletteColor(theme, "@danger").?);
    try std.testing.expect(resolvePaletteSlot(theme, "missing") == null);
}

test "rejects palette reference cycles" {
    const source =
        \\version = 1
        \\name = "cycle"
        \\
        \\[palette]
        \\a = "@b"
        \\b = "@a"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expect(resolvePaletteSlot(theme, "a") == null);
}

test "validates theme schema" {
    const source =
        \\version = 1
        \\name = "valid"
        \\
        \\[palette]
        \\fg = "15"
        \\muted = "8"
        \\accent = "@fg"
        \\success = "10"
        \\warning = "11"
        \\danger = "#ff0000"
        \\
        \\[segments.cwd]
        \\fg = "@accent"
        \\style = "bold"
        \\
        \\[segments.git_branch]
        \\fg = "@success"
        \\
        \\[segments.exit_status]
        \\fg = "@danger"
        \\
        \\[segments.jobs]
        \\fg = "@warning"
        \\
        \\[segments.cmd_duration]
        \\fg = "@muted"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    const failures = try validateAlloc(std.testing.allocator, theme);
    defer std.testing.allocator.free(failures);
    try std.testing.expectEqual(@as(usize, 0), failures.len);
}

test "reports theme validation failures" {
    const source =
        \\version = 1
        \\name = "Bad"
        \\
        \\[palette]
        \\fg = "@missing"
        \\muted = "8"
        \\accent = "15"
        \\success = "10"
        \\warning = "11"
        \\danger = "9"
        \\custom = "14"
        \\
        \\[segments.cwd]
        \\fg = "@custom"
        \\style = "sparkle"
        \\glyph = "→"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    const failures = try validateAlloc(std.testing.allocator, theme);
    defer std.testing.allocator.free(failures);
    try std.testing.expect(failures.len >= 6);
    const report = try formatValidationFailuresAlloc(std.testing.allocator, failures);
    defer std.testing.allocator.free(report);
    try std.testing.expect(std.mem.indexOf(u8, report, "theme.name: invalid theme name") != null);
    try std.testing.expect(std.mem.indexOf(u8, report, "cwd.style: invalid style") != null);
    try std.testing.expect(std.mem.indexOf(u8, report, "cwd.ascii: missing ASCII fallback") != null);
}

test "reports theme parse spans" {
    const source =
        \\version = 1
        \\name = "bad"
        \\
        \\[capabilities]
        \\color = "rgb"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    try std.testing.expectError(error.InvalidTheme, parse(std.testing.allocator, source, &diagnostic));
    try std.testing.expectEqual(@as(usize, 5), diagnostic.line);
    try std.testing.expectEqual(@as(usize, 9), diagnostic.column);
    try std.testing.expectEqualStrings("invalid color capability", diagnostic.message);
}
