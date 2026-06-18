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

pub const GlyphTier = enum {
    nerdfont,
    unicode,
    ascii,
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

pub const LayoutLine = struct {
    left: [][]u8,
    right: [][]u8,
};

pub const Layout = struct {
    lines: []LayoutLine,

    pub fn deinit(self: *Layout, allocator: std.mem.Allocator) void {
        freeLayoutLines(allocator, self.lines);
        self.* = undefined;
    }
};

pub const Segment = struct {
    id: []u8,
    fg: []u8 = "",
    bg: []u8 = "",
    style: []u8 = "",
    glyph: []u8 = "",
    unicode: []u8 = "",
    ascii: []u8 = "",
    a11y: []u8 = "",
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
    layout: Layout,
    segments: []Segment,

    pub fn deinit(self: *Theme, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.extends);
        freePalette(allocator, self.palette);
        var separators = self.separators;
        separators.deinit(allocator);
        var layout = self.layout;
        layout.deinit(allocator);
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
    layout,
    layout_line: usize,
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

const LayoutLineBuilder = struct {
    left: ?[][]u8 = null,
    right: ?[][]u8 = null,
    seen_left: bool = false,
    seen_right: bool = false,

    fn hasKeys(self: LayoutLineBuilder) bool {
        return self.seen_left or self.seen_right;
    }

    fn deinit(self: *LayoutLineBuilder, allocator: std.mem.Allocator) void {
        if (self.left) |value| freeStringArray(allocator, value);
        if (self.right) |value| freeStringArray(allocator, value);
        self.* = .{};
    }

    fn finish(self: *LayoutLineBuilder, allocator: std.mem.Allocator) !LayoutLine {
        const left = if (self.left) |value| value else try allocator.alloc([]u8, 0);
        self.left = null;
        errdefer freeStringArray(allocator, left);
        const right = if (self.right) |value| value else try allocator.alloc([]u8, 0);
        self.right = null;
        return .{ .left = left, .right = right };
    }
};

const LayoutLineSlot = struct {
    index: usize,
    line: LayoutLineBuilder = .{},
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

pub fn resolveSegmentGlyph(segment: Segment, tier: GlyphTier) []const u8 {
    return switch (tier) {
        .nerdfont => firstNonEmpty(&.{ segment.glyph, segment.unicode, segment.ascii }),
        .unicode => if (segment.unicode.len > 0)
            segment.unicode
        else if (segment.glyph.len > 0 and !hasPrivateUseCodepoint(segment.glyph))
            segment.glyph
        else
            segment.ascii,
        .ascii => segment.ascii,
    };
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
        if (item.a11y.len == 0) {
            try failures.append(allocator, .{ .section = item.id, .key = "a11y", .message = "missing a11y label" });
        }
        if ((item.glyph.len > 0 or item.unicode.len > 0) and item.ascii.len == 0) {
            try failures.append(allocator, .{ .section = item.id, .key = "ascii", .message = "missing ASCII fallback" });
        }
        if (hasPrivateUseCodepoint(item.glyph) and item.unicode.len == 0) {
            try failures.append(allocator, .{ .section = item.id, .key = "unicode", .message = "missing Unicode fallback" });
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
    layout_root: LayoutLineBuilder = .{},
    layout_lines: std.ArrayList(LayoutLineSlot) = .empty,
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
        const layout = try self.finishLayout();
        errdefer {
            var cleanup = layout;
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
            .layout = layout,
            .segments = segments,
        };
    }

    fn deinitWorking(self: *Parser) void {
        if (self.name) |value| self.allocator.free(value);
        if (self.extends) |value| self.allocator.free(value);
        self.separators.deinit(self.allocator);
        self.layout_root.deinit(self.allocator);
        for (self.layout_lines.items) |*slot| {
            slot.line.deinit(self.allocator);
        }
        self.layout_lines.deinit(self.allocator);
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
            .layout => try self.parseLayoutKey(line_no, &self.layout_root, key, value),
            .layout_line => |line_index| {
                var line = try self.layoutLineForIndex(line_index);
                try self.parseLayoutKey(line_no, &line.line, key, value);
            },
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

    fn parseLayoutKey(self: *Parser, line_no: usize, line: *LayoutLineBuilder, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "left")) {
            try self.setLayoutModules(&line.left, &line.seen_left, line_no, key.column, value);
        } else if (std.mem.eql(u8, key.text, "right")) {
            try self.setLayoutModules(&line.right, &line.seen_right, line_no, key.column, value);
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
        } else if (std.mem.eql(u8, key.text, "unicode")) {
            try self.setSegmentString(&current_segment.unicode, line_no, value);
        } else if (std.mem.eql(u8, key.text, "ascii")) {
            try self.setSegmentString(&current_segment.ascii, line_no, value);
        } else if (std.mem.eql(u8, key.text, "a11y")) {
            try self.setSegmentString(&current_segment.a11y, line_no, value);
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

    fn setLayoutModules(self: *Parser, target: *?[][]u8, seen: *bool, line_no: usize, column: usize, value: Trimmed) !void {
        try self.markUnseen(seen, line_no, column);
        target.* = try self.parseStringArrayAlloc(value, line_no);
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
        const unicode = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(unicode);
        const ascii = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(ascii);
        const a11y = try self.allocator.dupe(u8, "");
        errdefer self.allocator.free(a11y);
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
            .unicode = unicode,
            .ascii = ascii,
            .a11y = a11y,
            .prefix = prefix,
            .suffix = suffix,
        };
    }

    fn layoutLineForIndex(self: *Parser, index: usize) !*LayoutLineSlot {
        for (self.layout_lines.items) |*slot| {
            if (slot.index == index) return slot;
        }
        const insert_at = for (self.layout_lines.items, 0..) |slot, slot_index| {
            if (index < slot.index) break slot_index;
        } else self.layout_lines.items.len;
        try self.layout_lines.insert(self.allocator, insert_at, .{ .index = index });
        return &self.layout_lines.items[insert_at];
    }

    fn finishLayout(self: *Parser) !Layout {
        if (self.layout_root.hasKeys() and self.layout_lines.items.len > 0) {
            return self.fail(1, 1, "mixed layout tables");
        }
        if (self.layout_lines.items.len > 0) {
            var lines = try self.allocator.alloc(LayoutLine, self.layout_lines.items.len);
            var initialized: usize = 0;
            errdefer {
                for (lines[0..initialized]) |*line| {
                    freeStringArray(self.allocator, line.left);
                    freeStringArray(self.allocator, line.right);
                }
                self.allocator.free(lines);
            }
            for (self.layout_lines.items, 0..) |*slot, index| {
                lines[index] = try slot.line.finish(self.allocator);
                initialized += 1;
            }
            self.layout_lines.deinit(self.allocator);
            self.layout_lines = .empty;
            return .{ .lines = lines };
        }
        if (self.layout_root.hasKeys()) {
            const lines = try self.allocator.alloc(LayoutLine, 1);
            errdefer self.allocator.free(lines);
            lines[0] = try self.layout_root.finish(self.allocator);
            return .{ .lines = lines };
        }
        return .{ .lines = try self.allocator.alloc(LayoutLine, 0) };
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

    fn parseStringArrayAlloc(self: *Parser, value: Trimmed, line_no: usize) ![][]u8 {
        if (value.text.len < 2 or value.text[0] != '[' or value.text[value.text.len - 1] != ']') {
            return self.fail(line_no, value.column, "expected array");
        }

        var items: std.ArrayList([]u8) = .empty;
        errdefer {
            for (items.items) |item| self.allocator.free(item);
            items.deinit(self.allocator);
        }

        var index: usize = 1;
        while (index < value.text.len - 1) {
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != '"') return self.fail(line_no, value.column + index, "expected string");
            const start = index;
            index += 1;
            var escaped = false;
            while (index < value.text.len - 1) : (index += 1) {
                if (escaped) {
                    escaped = false;
                    continue;
                }
                if (value.text[index] == '\\') {
                    escaped = true;
                    continue;
                }
                if (value.text[index] == '"') break;
            }
            if (index >= value.text.len - 1) return self.fail(line_no, value.column + start, "unterminated string");
            const item = try self.parseStringAlloc(.{ .text = value.text[start .. index + 1], .column = value.column + start }, line_no);
            errdefer self.allocator.free(item);
            try items.append(self.allocator, item);
            index += 1;
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != ',') return self.fail(line_no, value.column + index, "expected comma");
            index += 1;
        }

        return items.toOwnedSlice(self.allocator);
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
    if (std.mem.eql(u8, name, "layout")) return .layout;
    if (std.mem.startsWith(u8, name, "layout.line.")) {
        const raw_index = name["layout.line.".len..];
        if (raw_index.len == 0) return null;
        const index = std.fmt.parseInt(usize, raw_index, 10) catch return null;
        return .{ .layout_line = index };
    }
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

fn firstNonEmpty(values: []const []const u8) []const u8 {
    for (values) |value| {
        if (value.len > 0) return value;
    }
    return "";
}

fn hasPrivateUseCodepoint(value: []const u8) bool {
    var index: usize = 0;
    while (index < value.len) {
        const view = std.unicode.Utf8View.init(value[index..]) catch return true;
        var iterator = view.iterator();
        const codepoint = iterator.nextCodepoint() orelse return false;
        if ((codepoint >= 0xe000 and codepoint <= 0xf8ff) or
            (codepoint >= 0xf0000 and codepoint <= 0xffffd) or
            (codepoint >= 0x100000 and codepoint <= 0x10fffd))
        {
            return true;
        }
        index += iterator.i;
    }
    return false;
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

fn skipSpaces(value: []const u8, index: *usize) void {
    while (index.* < value.len and isSpace(value[index.*])) : (index.* += 1) {}
}

fn isSpace(byte: u8) bool {
    return byte == ' ' or byte == '\t' or byte == '\r' or byte == '\n';
}

fn freeStringArray(allocator: std.mem.Allocator, values: [][]u8) void {
    for (values) |value| allocator.free(value);
    allocator.free(values);
}

fn freeLayoutLines(allocator: std.mem.Allocator, lines: []LayoutLine) void {
    for (lines) |line| {
        freeStringArray(allocator, line.left);
        freeStringArray(allocator, line.right);
    }
    allocator.free(lines);
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
    allocator.free(item.unicode);
    allocator.free(item.ascii);
    allocator.free(item.a11y);
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

test "parses single-line layout" {
    const source =
        \\version = 1
        \\name = "layout"
        \\
        \\[layout]
        \\left = ["cwd", "git_branch"]
        \\right = ["time"]
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 1), theme.layout.lines.len);
    try std.testing.expectEqual(@as(usize, 2), theme.layout.lines[0].left.len);
    try std.testing.expectEqualStrings("cwd", theme.layout.lines[0].left[0]);
    try std.testing.expectEqualStrings("git_branch", theme.layout.lines[0].left[1]);
    try std.testing.expectEqualStrings("time", theme.layout.lines[0].right[0]);
}

test "parses indexed multi-line layout" {
    const source =
        \\version = 1
        \\name = "layout-lines"
        \\
        \\[layout.line.1]
        \\left = ["exit_status"]
        \\right = ["cmd_duration"]
        \\
        \\[layout.line.0]
        \\left = ["cwd", "git_branch"]
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 2), theme.layout.lines.len);
    try std.testing.expectEqualStrings("cwd", theme.layout.lines[0].left[0]);
    try std.testing.expectEqualStrings("git_branch", theme.layout.lines[0].left[1]);
    try std.testing.expectEqualStrings("exit_status", theme.layout.lines[1].left[0]);
    try std.testing.expectEqualStrings("cmd_duration", theme.layout.lines[1].right[0]);
}

test "resolves glyph tiers" {
    var empty: [0]u8 = .{};
    var private_glyph = [_]u8{ 0xee, 0x82, 0xa0 };
    var git_unicode = [_]u8{ 'g', 'i', 't' };
    var git_ascii = [_]u8{ 'g', 'i', 't', ':' };
    const segment_with_private_glyph = Segment{
        .id = empty[0..],
        .fg = empty[0..],
        .bg = empty[0..],
        .style = empty[0..],
        .glyph = private_glyph[0..],
        .unicode = git_unicode[0..],
        .ascii = git_ascii[0..],
        .prefix = empty[0..],
        .suffix = empty[0..],
    };
    try std.testing.expectEqualStrings("\xee\x82\xa0", resolveSegmentGlyph(segment_with_private_glyph, .nerdfont));
    try std.testing.expectEqualStrings("git", resolveSegmentGlyph(segment_with_private_glyph, .unicode));
    try std.testing.expectEqualStrings("git:", resolveSegmentGlyph(segment_with_private_glyph, .ascii));

    var arrow = [_]u8{ 0xe2, 0x86, 0x92 };
    var ascii_arrow = [_]u8{ '-', '>' };
    const segment_with_unicode_glyph = Segment{
        .id = empty[0..],
        .fg = empty[0..],
        .bg = empty[0..],
        .style = empty[0..],
        .glyph = arrow[0..],
        .unicode = empty[0..],
        .ascii = ascii_arrow[0..],
        .prefix = empty[0..],
        .suffix = empty[0..],
    };
    try std.testing.expectEqualStrings("\xe2\x86\x92", resolveSegmentGlyph(segment_with_unicode_glyph, .unicode));
}

test "fuzz theme render state invariants" {
    return std.testing.fuzz({}, fuzzThemeRenderState, .{
        .corpus = &.{
            "",
            "version = 1\nname = \"minimal\"\n",
            \\version = 1
            \\name = "fuzz"
            \\
            \\[capabilities]
            \\color = "ansi256"
            \\glyphs = "ascii"
            \\
            \\[palette]
            \\fg = "#ffffff"
            \\muted = "8"
            \\accent = "39"
            \\success = "34"
            \\warning = "220"
            \\danger = "196"
            \\
            \\[segments.cwd]
            \\fg = "@accent"
            \\glyph = ">"
            \\ascii = "cwd:"
            \\
        },
    });
}

fn fuzzThemeRenderState(_: void, input: []const u8) !void {
    if (input.len > 4096) return;
    var diagnostic: Diagnostic = .{};
    var theme = parse(std.testing.allocator, input, &diagnostic) catch return;
    defer theme.deinit(std.testing.allocator);

    const failures = try validateAlloc(std.testing.allocator, theme);
    defer std.testing.allocator.free(failures);
    if (failures.len != 0) return;

    const color_caps = [_]contrast.ColorCaps{ .none, .@"16", .@"256", .truecolor };
    const glyph_tiers = [_]GlyphTier{ .ascii, .unicode, .nerdfont };

    for (theme.segments) |segment| {
        for (color_caps) |cap| {
            try formatSegmentColorRef(segment.fg, theme, cap, .foreground);
            try formatSegmentColorRef(segment.bg, theme, cap, .background);
        }
        for (glyph_tiers) |tier| {
            _ = resolveSegmentGlyph(segment, tier);
        }
    }
}

fn formatSegmentColorRef(ref: []const u8, theme: Theme, cap: contrast.ColorCaps, role: contrast.ColorRole) !void {
    if (ref.len == 0) return;
    const rgb = resolvePaletteColor(theme, ref) orelse return;
    const sgr = try contrast.formatSgrColorAlloc(std.testing.allocator, role, rgb, cap);
    std.testing.allocator.free(sgr);
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
        \\a11y = "current directory"
        \\
        \\[segments.git_branch]
        \\fg = "@success"
        \\a11y = "git branch"
        \\
        \\[segments.exit_status]
        \\fg = "@danger"
        \\a11y = "exit status"
        \\
        \\[segments.jobs]
        \\fg = "@warning"
        \\a11y = "background jobs"
        \\
        \\[segments.cmd_duration]
        \\fg = "@muted"
        \\a11y = "command duration"
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

test "requires declared glyph fallbacks" {
    const source =
        \\version = 1
        \\name = "fallbacks"
        \\
        \\[palette]
        \\fg = "15"
        \\muted = "8"
        \\accent = "14"
        \\success = "10"
        \\warning = "11"
        \\danger = "9"
        \\
        \\[segments.cwd]
        \\fg = "@accent"
        \\glyph = ""
        \\ascii = "git:"
        \\a11y = "current directory"
        \\
        \\[segments.git_branch]
        \\fg = "@success"
        \\unicode = "git"
        \\a11y = "git branch"
        \\
        \\[segments.exit_status]
        \\fg = "@danger"
        \\a11y = "exit status"
        \\
        \\[segments.jobs]
        \\fg = "@warning"
        \\a11y = "background jobs"
        \\
        \\[segments.cmd_duration]
        \\fg = "@muted"
        \\a11y = "command duration"
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var theme = try parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);

    const failures = try validateAlloc(std.testing.allocator, theme);
    defer std.testing.allocator.free(failures);
    try std.testing.expectEqual(@as(usize, 2), failures.len);
    const report = try formatValidationFailuresAlloc(std.testing.allocator, failures);
    defer std.testing.allocator.free(report);
    try std.testing.expect(std.mem.indexOf(u8, report, "cwd.unicode: missing Unicode fallback") != null);
    try std.testing.expect(std.mem.indexOf(u8, report, "git_branch.ascii: missing ASCII fallback") != null);
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
