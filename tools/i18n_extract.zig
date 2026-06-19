const std = @import("std");

const max_source_bytes = 4 * 1024 * 1024;

const Reference = struct {
    path: []const u8,
    line: usize,
};

const Message = struct {
    text: []u8,
    refs: std.ArrayList(Reference) = .empty,

    fn deinit(self: *Message, allocator: std.mem.Allocator) void {
        allocator.free(self.text);
        for (self.refs.items) |ref| allocator.free(ref.path);
        self.refs.deinit(allocator);
    }
};

const Catalog = struct {
    messages: std.ArrayList(Message) = .empty,
    index: std.StringHashMap(usize),

    fn init(allocator: std.mem.Allocator) Catalog {
        return .{ .index = std.StringHashMap(usize).init(allocator) };
    }

    fn deinit(self: *Catalog, allocator: std.mem.Allocator) void {
        for (self.messages.items) |*message| message.deinit(allocator);
        self.messages.deinit(allocator);
        self.index.deinit();
    }

    fn addOwned(self: *Catalog, allocator: std.mem.Allocator, text: []u8, ref: Reference) !void {
        errdefer allocator.free(text);
        if (!hasUserFacingText(text)) {
            allocator.free(text);
            return;
        }
        const owned_ref = try ownedReference(allocator, ref);
        errdefer allocator.free(owned_ref.path);
        if (self.index.get(text)) |index| {
            try self.messages.items[index].refs.append(allocator, owned_ref);
            allocator.free(text);
            return;
        }
        var refs: std.ArrayList(Reference) = .empty;
        errdefer refs.deinit(allocator);
        try refs.append(allocator, owned_ref);
        try self.index.put(text, self.messages.items.len);
        try self.messages.append(allocator, .{ .text = text, .refs = refs });
    }
};

fn ownedReference(allocator: std.mem.Allocator, ref: Reference) !Reference {
    return .{ .path = try allocator.dupe(u8, ref.path), .line = ref.line };
}

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);
    if (args.len < 4) return error.MissingI18nExtractArgs;

    const cwd_path = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd_path);

    var catalog = Catalog.init(allocator);
    defer catalog.deinit(allocator);

    for (args[3..]) |path| {
        const source = try std.fs.cwd().readFileAlloc(allocator, path, max_source_bytes);
        defer allocator.free(source);
        const display_path = try displayPathAlloc(allocator, cwd_path, path);
        defer allocator.free(display_path);
        try extractFromSource(allocator, &catalog, display_path, source);
    }

    const pot = try catalogTextAlloc(allocator, catalog.messages.items, .pot);
    defer allocator.free(pot);
    const po = try catalogTextAlloc(allocator, catalog.messages.items, .en_us);
    defer allocator.free(po);

    try writeFile(args[1], pot);
    try writeFile(args[2], po);
}

fn writeFile(path: []const u8, contents: []const u8) !void {
    if (std.fs.path.dirname(path)) |dir| try std.fs.cwd().makePath(dir);
    var file = try std.fs.cwd().createFile(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(contents);
}

fn displayPathAlloc(allocator: std.mem.Allocator, cwd_path: []const u8, path: []const u8) ![]u8 {
    if (std.fs.path.isAbsolute(path) and
        path.len > cwd_path.len and
        path[cwd_path.len] == '/' and
        std.mem.startsWith(u8, path, cwd_path))
    {
        return allocator.dupe(u8, path[cwd_path.len + 1 ..]);
    }
    return allocator.dupe(u8, path);
}

fn extractFromSource(allocator: std.mem.Allocator, catalog: *Catalog, path: []const u8, source: []const u8) !void {
    var lines = std.mem.splitScalar(u8, source, '\n');
    var line_no: usize = 1;
    var in_help_block = false;
    var help_start_line: usize = 0;
    var help_text: std.ArrayList(u8) = .empty;
    defer help_text.deinit(allocator);

    while (lines.next()) |raw_line| : (line_no += 1) {
        const line = std.mem.trimRight(u8, raw_line, "\r");
        if (in_help_block) {
            const trimmed = std.mem.trimLeft(u8, line, " \t");
            if (std.mem.startsWith(u8, trimmed, "\\\\")) {
                if (help_text.items.len == 0) help_start_line = line_no;
                try help_text.appendSlice(allocator, trimmed[2..]);
                try help_text.append(allocator, '\n');
                continue;
            }
            if (std.mem.startsWith(u8, trimmed, ";")) {
                if (help_text.items.len > 0) {
                    try catalog.addOwned(allocator, try help_text.toOwnedSlice(allocator), .{ .path = path, .line = help_start_line });
                    help_text = .empty;
                }
                in_help_block = false;
                continue;
            }
        }

        if (isHelpTextConst(line)) {
            in_help_block = true;
            help_start_line = line_no + 1;
            continue;
        }
        try extractWriteAllLiterals(allocator, catalog, path, line, line_no);
    }

    if (in_help_block and help_text.items.len > 0) {
        try catalog.addOwned(allocator, try help_text.toOwnedSlice(allocator), .{ .path = path, .line = help_start_line });
        help_text = .empty;
    }
}

fn isHelpTextConst(line: []const u8) bool {
    const trimmed = std.mem.trimLeft(u8, line, " \t");
    return std.mem.startsWith(u8, trimmed, "const ") and
        std.mem.indexOf(u8, trimmed, "help_text") != null and
        std.mem.indexOfScalar(u8, trimmed, '=') != null;
}

fn extractWriteAllLiterals(allocator: std.mem.Allocator, catalog: *Catalog, path: []const u8, line: []const u8, line_no: usize) !void {
    const needle = "writeAll(\"";
    var offset: usize = 0;
    while (std.mem.indexOf(u8, line[offset..], needle)) |relative| {
        const literal_start = offset + relative + needle.len;
        const parsed = parseZigStringLiteralAlloc(allocator, line[literal_start..]) catch {
            offset = literal_start;
            continue;
        };
        if (isLiteralOnlyWriteAllTail(line[literal_start + parsed.consumed ..]) and std.mem.indexOfScalar(u8, parsed.text, '\n') != null) {
            try catalog.addOwned(allocator, parsed.text, .{ .path = path, .line = line_no });
        } else {
            allocator.free(parsed.text);
        }
        offset = literal_start + parsed.consumed;
    }
}

const ParsedLiteral = struct {
    text: []u8,
    consumed: usize,
};

fn parseZigStringLiteralAlloc(allocator: std.mem.Allocator, source_after_quote: []const u8) !ParsedLiteral {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var index: usize = 0;
    while (index < source_after_quote.len) : (index += 1) {
        const byte = source_after_quote[index];
        if (byte == '"') {
            return .{ .text = try out.toOwnedSlice(allocator), .consumed = index + 1 };
        }
        if (byte != '\\') {
            try out.append(allocator, byte);
            continue;
        }
        index += 1;
        if (index >= source_after_quote.len) return error.UnterminatedEscape;
        const escaped = source_after_quote[index];
        switch (escaped) {
            'n' => try out.append(allocator, '\n'),
            'r' => try out.append(allocator, '\r'),
            't' => try out.append(allocator, '\t'),
            '\\' => try out.append(allocator, '\\'),
            '"' => try out.append(allocator, '"'),
            else => return error.UnsupportedEscape,
        }
    }
    return error.UnterminatedString;
}

fn isLiteralOnlyWriteAllTail(tail: []const u8) bool {
    const close = std.mem.indexOfScalar(u8, tail, ')') orelse return false;
    for (tail[0..close]) |byte| {
        if (byte != ' ' and byte != '\t') return false;
    }
    return true;
}

fn hasUserFacingText(text: []const u8) bool {
    const trimmed = std.mem.trim(u8, text, " \t\r\n");
    if (trimmed.len < 2) return false;
    if (trimmed[0] == '{' and trimmed[trimmed.len - 1] == '}') return false;
    for (trimmed) |byte| {
        if (std.ascii.isAlphabetic(byte)) return true;
    }
    return false;
}

const CatalogKind = enum {
    pot,
    en_us,
};

fn catalogTextAlloc(allocator: std.mem.Allocator, messages: []const Message, kind: CatalogKind) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try appendHeader(allocator, &out, kind);
    for (messages) |message| {
        try out.append(allocator, '\n');
        try appendReferences(allocator, &out, message.refs.items);
        try out.appendSlice(allocator, "msgid \"\"\n");
        try appendPoString(allocator, &out, message.text);
        try out.appendSlice(allocator, "msgstr \"\"\n");
        if (kind == .en_us) try appendPoString(allocator, &out, message.text);
    }
    return out.toOwnedSlice(allocator);
}

fn appendHeader(allocator: std.mem.Allocator, out: *std.ArrayList(u8), kind: CatalogKind) !void {
    const title = switch (kind) {
        .pot => "Shisa message catalog template.",
        .en_us => "English (United States) translations for Shisa.",
    };
    const language_team = switch (kind) {
        .pot => "Shisa contributors <security@shisa.sh>",
        .en_us => "English (United States) <security@shisa.sh>",
    };
    const language = switch (kind) {
        .pot => "",
        .en_us => "en_US",
    };
    try appendFmt(allocator, out,
        \\# {s}
        \\# Copyright (C) 2026 Shisa contributors
        \\# This file is distributed under the same license as Shisa.
        \\#
        \\msgid ""
        \\msgstr ""
        \\"Project-Id-Version: shisa 0.1.0\n"
        \\"Report-Msgid-Bugs-To: security@shisa.sh\n"
        \\"POT-Creation-Date: 2026-06-19 00:00+0000\n"
        \\"PO-Revision-Date: 2026-06-19 00:00+0000\n"
        \\"Last-Translator: Shisa contributors <security@shisa.sh>\n"
        \\"Language-Team: {s}\n"
        \\"Language: {s}\n"
        \\"MIME-Version: 1.0\n"
        \\"Content-Type: text/plain; charset=UTF-8\n"
        \\"Content-Transfer-Encoding: 8bit\n"
        \\
    , .{ title, language_team, language });
    if (kind == .en_us) {
        try out.appendSlice(allocator, "\"Plural-Forms: nplurals=2; plural=(n != 1);\\n\"\n");
    }
}

fn appendReferences(allocator: std.mem.Allocator, out: *std.ArrayList(u8), refs: []const Reference) !void {
    try out.appendSlice(allocator, "#:");
    for (refs) |ref| try appendFmt(allocator, out, " {s}:{d}", .{ ref.path, ref.line });
    try out.append(allocator, '\n');
}

fn appendPoString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), text: []const u8) !void {
    var start: usize = 0;
    while (start < text.len) {
        if (std.mem.indexOfScalar(u8, text[start..], '\n')) |relative| {
            try appendPoQuotedLine(allocator, out, text[start .. start + relative + 1]);
            start += relative + 1;
        } else {
            try appendPoQuotedLine(allocator, out, text[start..]);
            break;
        }
    }
}

fn appendPoQuotedLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), text: []const u8) !void {
    try out.append(allocator, '"');
    for (text) |byte| {
        switch (byte) {
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '"' => try out.appendSlice(allocator, "\\\""),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }
    try out.appendSlice(allocator, "\"\n");
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
}

test "extracts help blocks and literal writeAll messages" {
    const source =
        \\const help_text =
        \\    \\usage: shisa test
        \\    \\
        \\;
        \\pub fn main() !void {
        \\    try std.fs.File.stderr().writeAll("shisa: bad input\n");
        \\    try std.fs.File.stdout().writeAll("shisa " ++ version ++ "\n");
        \\}
    ;
    var catalog = Catalog.init(std.testing.allocator);
    defer catalog.deinit(std.testing.allocator);
    try extractFromSource(std.testing.allocator, &catalog, "src/main.zig", source);
    try std.testing.expectEqual(@as(usize, 2), catalog.messages.items.len);
    try std.testing.expectEqualStrings("usage: shisa test\n\n", catalog.messages.items[0].text);
    try std.testing.expectEqualStrings("shisa: bad input\n", catalog.messages.items[1].text);
}

test "writes gettext escaped strings" {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(std.testing.allocator);
    try appendPoString(std.testing.allocator, &out, "say \"hi\"\\now\n");
    try std.testing.expectEqualStrings("\"say \\\"hi\\\"\\\\now\\n\"\n", out.items);
}
