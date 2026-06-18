const std = @import("std");

pub const WatchedMtime = struct {
    path: []const u8,
    mtime_ns: i128,
};

pub const KeyInput = struct {
    cmd: []const u8,
    args: []const []const u8 = &.{},
    cwd: []const u8,
    mtimes: []const WatchedMtime = &.{},
};

pub const Entry = union(enum) {
    output: []const u8,
    missing_tool: []const u8,
};

const StoredKind = enum {
    output,
    missing_tool,
};

const StoredEntry = struct {
    key: []u8,
    value: []u8,
    kind: StoredKind,
};

pub const Store = struct {
    allocator: std.mem.Allocator,
    entries: std.StringHashMap(StoredEntry),

    pub fn init(allocator: std.mem.Allocator) Store {
        return .{
            .allocator = allocator,
            .entries = std.StringHashMap(StoredEntry).init(allocator),
        };
    }

    pub fn deinit(self: *Store) void {
        var it = self.entries.iterator();
        while (it.next()) |entry| freeStored(self.allocator, entry.value_ptr.*);
        self.entries.deinit();
        self.* = undefined;
    }

    pub fn putOutput(self: *Store, input: KeyInput, output: []const u8) !void {
        try self.put(input, .output, output);
    }

    pub fn putMissingTool(self: *Store, input: KeyInput, tool: []const u8) !void {
        try self.put(input, .missing_tool, tool);
    }

    pub fn get(self: *Store, input: KeyInput) !?Entry {
        const key = try keyAlloc(self.allocator, input);
        defer self.allocator.free(key);
        const entry = self.entries.get(key) orelse return null;
        return switch (entry.kind) {
            .output => .{ .output = entry.value },
            .missing_tool => .{ .missing_tool = entry.value },
        };
    }

    pub fn count(self: *Store) usize {
        return self.entries.count();
    }

    fn put(self: *Store, input: KeyInput, kind: StoredKind, value_source: []const u8) !void {
        const key = try keyAlloc(self.allocator, input);
        errdefer self.allocator.free(key);
        const value = try self.allocator.dupe(u8, value_source);
        errdefer self.allocator.free(value);

        const entry = try self.entries.getOrPut(key);
        if (entry.found_existing) {
            self.allocator.free(key);
            self.allocator.free(entry.value_ptr.value);
            entry.value_ptr.value = value;
            entry.value_ptr.kind = kind;
        } else {
            entry.value_ptr.* = .{ .key = key, .value = value, .kind = kind };
        }
    }
};

pub fn keyAlloc(allocator: std.mem.Allocator, input: KeyInput) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    const sorted_mtimes = try allocator.dupe(WatchedMtime, input.mtimes);
    defer allocator.free(sorted_mtimes);
    std.mem.sort(WatchedMtime, sorted_mtimes, {}, lessThanWatchedMtime);

    try appendString(allocator, &out, "cmd", input.cmd);
    try appendInt(allocator, &out, "argc", input.args.len);
    for (input.args) |arg| try appendString(allocator, &out, "arg", arg);
    try appendString(allocator, &out, "cwd", input.cwd);
    try appendInt(allocator, &out, "mtimec", sorted_mtimes.len);
    for (sorted_mtimes) |mtime| {
        try appendString(allocator, &out, "path", mtime.path);
        try appendInt(allocator, &out, "mtime", mtime.mtime_ns);
    }

    return out.toOwnedSlice(allocator);
}

fn lessThanWatchedMtime(_: void, a: WatchedMtime, b: WatchedMtime) bool {
    if (std.mem.eql(u8, a.path, b.path)) return a.mtime_ns < b.mtime_ns;
    return std.mem.lessThan(u8, a.path, b.path);
}

fn appendString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: []const u8) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}:", .{value.len});
    try out.appendSlice(allocator, value);
    try out.append(allocator, '|');
}

fn appendInt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: anytype) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}", .{value});
    try out.append(allocator, '|');
}

fn freeStored(allocator: std.mem.Allocator, entry: StoredEntry) void {
    allocator.free(entry.key);
    allocator.free(entry.value);
}

test "keys include command args cwd and mtimes" {
    const allocator = std.testing.allocator;
    const base = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(base);
    const changed_arg = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"-V"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(changed_arg);
    const changed_cwd = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/other",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 10 }},
    });
    defer allocator.free(changed_cwd);
    const changed_mtime = try keyAlloc(allocator, .{
        .cmd = "python3",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/pyproject.toml", .mtime_ns = 11 }},
    });
    defer allocator.free(changed_mtime);

    try std.testing.expect(!std.mem.eql(u8, base, changed_arg));
    try std.testing.expect(!std.mem.eql(u8, base, changed_cwd));
    try std.testing.expect(!std.mem.eql(u8, base, changed_mtime));
}

test "mtime key order is deterministic" {
    const allocator = std.testing.allocator;
    const first = try keyAlloc(allocator, .{
        .cmd = "node",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{
            .{ .path = "/repo/package.json", .mtime_ns = 2 },
            .{ .path = "/repo/.node-version", .mtime_ns = 1 },
        },
    });
    defer allocator.free(first);
    const second = try keyAlloc(allocator, .{
        .cmd = "node",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{
            .{ .path = "/repo/.node-version", .mtime_ns = 1 },
            .{ .path = "/repo/package.json", .mtime_ns = 2 },
        },
    });
    defer allocator.free(second);

    try std.testing.expectEqualStrings(first, second);
}

test "length prefixes prevent separator collisions" {
    const allocator = std.testing.allocator;
    const first = try keyAlloc(allocator, .{ .cmd = "ab", .args = &.{"c"}, .cwd = "/repo" });
    defer allocator.free(first);
    const second = try keyAlloc(allocator, .{ .cmd = "a", .args = &.{"bc"}, .cwd = "/repo" });
    defer allocator.free(second);
    try std.testing.expect(!std.mem.eql(u8, first, second));
}

test "caches missing tools negatively" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    const input = KeyInput{ .cmd = "python3", .args = &.{"--version"}, .cwd = "/repo" };
    try store.putMissingTool(input, "python3");

    const cached = (try store.get(input)).?;
    switch (cached) {
        .missing_tool => |tool| try std.testing.expectEqualStrings("python3", tool),
        .output => return error.ExpectedMissingTool,
    }
    try std.testing.expectEqual(@as(usize, 1), store.count());
}

test "negative cache entries are keyed by full command input" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    try store.putMissingTool(.{ .cmd = "node", .args = &.{"--version"}, .cwd = "/repo" }, "node");
    try std.testing.expect((try store.get(.{ .cmd = "node", .args = &.{"--version"}, .cwd = "/repo" })) != null);
    try std.testing.expect(try store.get(.{ .cmd = "node", .args = &.{"--version"}, .cwd = "/other" }) == null);
    try std.testing.expect(try store.get(.{ .cmd = "node", .args = &.{"-v"}, .cwd = "/repo" }) == null);
}
