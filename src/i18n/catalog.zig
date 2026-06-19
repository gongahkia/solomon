const std = @import("std");

pub const Message = struct {
    msgid: []u8,
    msgstr: []u8,
};

pub const Catalog = struct {
    messages: []Message,

    pub fn deinit(self: *Catalog, allocator: std.mem.Allocator) void {
        for (self.messages) |message| {
            allocator.free(message.msgid);
            allocator.free(message.msgstr);
        }
        allocator.free(self.messages);
        self.* = undefined;
    }

    pub fn lookup(self: Catalog, msgid: []const u8) ?[]const u8 {
        for (self.messages) |message| {
            if (std.mem.eql(u8, message.msgid, msgid) and message.msgstr.len > 0) return message.msgstr;
        }
        return null;
    }
};

pub fn parsePoAlloc(allocator: std.mem.Allocator, source: []const u8) !Catalog {
    var parser = Parser{
        .allocator = allocator,
    };
    defer parser.deinitWorking();
    try parser.parse(source);
    return .{ .messages = try parser.messages.toOwnedSlice(allocator) };
}

pub fn translateWithFallback(primary: ?Catalog, fallback: Catalog, msgid: []const u8) []const u8 {
    if (primary) |catalog| {
        if (catalog.lookup(msgid)) |translated| return translated;
    }
    if (fallback.lookup(msgid)) |translated| return translated;
    return msgid;
}

const Parser = struct {
    allocator: std.mem.Allocator,
    messages: std.ArrayList(Message) = .empty,
    msgid: std.ArrayList(u8) = .empty,
    msgstr: std.ArrayList(u8) = .empty,
    state: State = .none,
    have_msgid: bool = false,

    const State = enum {
        none,
        msgid,
        msgstr,
    };

    fn parse(self: *Parser, source: []const u8) !void {
        var lines = std.mem.splitScalar(u8, source, '\n');
        while (lines.next()) |raw_line| {
            const line = std.mem.trimRight(u8, raw_line, "\r");
            if (line.len == 0 or line[0] == '#') continue;
            if (std.mem.startsWith(u8, line, "msgid ")) {
                try self.finishMessage();
                self.state = .msgid;
                self.have_msgid = true;
                try self.appendPoString(&self.msgid, line["msgid ".len..]);
            } else if (std.mem.startsWith(u8, line, "msgstr ")) {
                if (!self.have_msgid) return error.InvalidPo;
                self.state = .msgstr;
                try self.appendPoString(&self.msgstr, line["msgstr ".len..]);
            } else if (line.len > 0 and line[0] == '"') {
                switch (self.state) {
                    .msgid => try self.appendPoString(&self.msgid, line),
                    .msgstr => try self.appendPoString(&self.msgstr, line),
                    .none => return error.InvalidPo,
                }
            } else {
                return error.InvalidPo;
            }
        }
        try self.finishMessage();
    }

    fn finishMessage(self: *Parser) !void {
        if (!self.have_msgid) return;
        const id = try self.msgid.toOwnedSlice(self.allocator);
        errdefer self.allocator.free(id);
        const value = try self.msgstr.toOwnedSlice(self.allocator);
        if (id.len == 0) {
            self.allocator.free(id);
            self.allocator.free(value);
        } else {
            errdefer self.allocator.free(id);
            errdefer self.allocator.free(value);
            try self.messages.append(self.allocator, .{ .msgid = id, .msgstr = value });
        }
        self.msgid = .empty;
        self.msgstr = .empty;
        self.state = .none;
        self.have_msgid = false;
    }

    fn appendPoString(self: *Parser, out: *std.ArrayList(u8), token: []const u8) !void {
        const text = std.mem.trim(u8, token, " \t");
        if (text.len < 2 or text[0] != '"' or text[text.len - 1] != '"') return error.InvalidPo;
        var index: usize = 1;
        while (index < text.len - 1) : (index += 1) {
            const byte = text[index];
            if (byte != '\\') {
                try out.append(self.allocator, byte);
                continue;
            }
            index += 1;
            if (index >= text.len - 1) return error.InvalidPo;
            switch (text[index]) {
                '"' => try out.append(self.allocator, '"'),
                '\\' => try out.append(self.allocator, '\\'),
                'n' => try out.append(self.allocator, '\n'),
                'r' => try out.append(self.allocator, '\r'),
                't' => try out.append(self.allocator, '\t'),
                else => return error.InvalidPo,
            }
        }
    }

    fn deinitWorking(self: *Parser) void {
        for (self.messages.items) |message| {
            self.allocator.free(message.msgid);
            self.allocator.free(message.msgstr);
        }
        self.messages.deinit(self.allocator);
        self.msgid.deinit(self.allocator);
        self.msgstr.deinit(self.allocator);
    }
};

test "parses gettext messages with multiline escapes" {
    const source =
        \\# header
        \\msgid ""
        \\msgstr ""
        \\"Content-Type: text/plain\n"
        \\
        \\#: src/main.zig:1
        \\msgid "hello\n"
        \\"world"
        \\msgstr "bonjour\n"
        \\"monde"
        \\
    ;
    var catalog = try parsePoAlloc(std.testing.allocator, source);
    defer catalog.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 1), catalog.messages.len);
    try std.testing.expectEqualStrings("hello\nworld", catalog.messages[0].msgid);
    try std.testing.expectEqualStrings("bonjour\nmonde", catalog.messages[0].msgstr);
}

test "translation falls through to en-US catalog" {
    const primary_source =
        \\msgid "hello"
        \\msgstr ""
        \\
        \\msgid "bye"
        \\msgstr "salut"
        \\
    ;
    const fallback_source =
        \\msgid "hello"
        \\msgstr "hello"
        \\
        \\msgid "missing-primary"
        \\msgstr "fallback"
        \\
    ;
    var primary = try parsePoAlloc(std.testing.allocator, primary_source);
    defer primary.deinit(std.testing.allocator);
    var fallback = try parsePoAlloc(std.testing.allocator, fallback_source);
    defer fallback.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("salut", translateWithFallback(primary, fallback, "bye"));
    try std.testing.expectEqualStrings("hello", translateWithFallback(primary, fallback, "hello"));
    try std.testing.expectEqualStrings("fallback", translateWithFallback(primary, fallback, "missing-primary"));
    try std.testing.expectEqualStrings("raw", translateWithFallback(primary, fallback, "raw"));
}
