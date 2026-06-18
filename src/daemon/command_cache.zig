const std = @import("std");
const fsnotify = @import("fsnotify.zig");

pub const WatchedMtime = struct {
    path: []const u8,
    mtime_ns: i128,
};

pub const KeyInput = struct {
    module_id: []const u8 = "",
    cmd: []const u8,
    args: []const []const u8 = &.{},
    cwd: []const u8,
    mtimes: []const WatchedMtime = &.{},
};

pub const ModuleTtl = struct {
    module_id: []const u8,
    ttl_ns: u64,
};

pub const Options = struct {
    max_entries: usize = 1024,
    default_ttl_ns: u64 = 5 * std.time.ns_per_min,
    module_ttls: []const ModuleTtl = &.{},
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
    module_id: []u8,
    cwd: []u8,
    value: []u8,
    kind: StoredKind,
    created_ns: u64,
    last_access_ns: u64,
};

pub const Store = struct {
    allocator: std.mem.Allocator,
    options: Options,
    entries: std.StringHashMap(StoredEntry),

    pub fn init(allocator: std.mem.Allocator) Store {
        return initWithOptions(allocator, .{});
    }

    pub fn initWithOptions(allocator: std.mem.Allocator, options: Options) Store {
        return .{
            .allocator = allocator,
            .options = options,
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
        try self.putOutputAt(input, output, nowNs());
    }

    pub fn putMissingTool(self: *Store, input: KeyInput, tool: []const u8) !void {
        try self.putMissingToolAt(input, tool, nowNs());
    }

    pub fn putOutputAt(self: *Store, input: KeyInput, output: []const u8, timestamp_ns: u64) !void {
        try self.putAt(input, .output, output, timestamp_ns);
    }

    pub fn putMissingToolAt(self: *Store, input: KeyInput, tool: []const u8, timestamp_ns: u64) !void {
        try self.putAt(input, .missing_tool, tool, timestamp_ns);
    }

    pub fn get(self: *Store, input: KeyInput) !?Entry {
        return self.getAt(input, nowNs());
    }

    pub fn getAt(self: *Store, input: KeyInput, timestamp_ns: u64) !?Entry {
        const key = try keyAlloc(self.allocator, input);
        defer self.allocator.free(key);
        const entry = self.entries.getPtr(key) orelse return null;
        if (self.isExpired(input.module_id, entry.created_ns, timestamp_ns)) {
            self.removeBorrowedKey(key);
            return null;
        }
        entry.last_access_ns = timestamp_ns;
        return switch (entry.kind) {
            .output => .{ .output = entry.value },
            .missing_tool => .{ .missing_tool = entry.value },
        };
    }

    pub fn count(self: *Store) usize {
        return self.entries.count();
    }

    pub fn invalidateModuleCwd(self: *Store, module_id: []const u8, cwd: []const u8) !void {
        var remove_keys: std.ArrayList([]u8) = .empty;
        defer {
            for (remove_keys.items) |key| self.allocator.free(key);
            remove_keys.deinit(self.allocator);
        }

        var it = self.entries.iterator();
        while (it.next()) |entry| {
            if (std.mem.eql(u8, entry.value_ptr.module_id, module_id) and std.mem.eql(u8, entry.value_ptr.cwd, cwd)) {
                try remove_keys.append(self.allocator, try self.allocator.dupe(u8, entry.key_ptr.*));
            }
        }

        for (remove_keys.items) |key| self.removeBorrowedKey(key);
    }

    fn putAt(self: *Store, input: KeyInput, kind: StoredKind, value_source: []const u8, timestamp_ns: u64) !void {
        const key = try keyAlloc(self.allocator, input);
        errdefer self.allocator.free(key);
        const module_id = try self.allocator.dupe(u8, input.module_id);
        errdefer self.allocator.free(module_id);
        const cwd = try self.allocator.dupe(u8, input.cwd);
        errdefer self.allocator.free(cwd);
        const value = try self.allocator.dupe(u8, value_source);
        errdefer self.allocator.free(value);

        const entry = try self.entries.getOrPut(key);
        if (entry.found_existing) {
            self.allocator.free(key);
            self.allocator.free(entry.value_ptr.module_id);
            self.allocator.free(entry.value_ptr.cwd);
            self.allocator.free(entry.value_ptr.value);
            entry.value_ptr.module_id = module_id;
            entry.value_ptr.cwd = cwd;
            entry.value_ptr.value = value;
            entry.value_ptr.kind = kind;
            entry.value_ptr.created_ns = timestamp_ns;
            entry.value_ptr.last_access_ns = timestamp_ns;
        } else {
            entry.value_ptr.* = .{
                .key = key,
                .module_id = module_id,
                .cwd = cwd,
                .value = value,
                .kind = kind,
                .created_ns = timestamp_ns,
                .last_access_ns = timestamp_ns,
            };
        }
        self.evictLru();
    }

    fn removeBorrowedKey(self: *Store, key: []const u8) void {
        const removed = self.entries.fetchRemove(key) orelse return;
        freeStored(self.allocator, removed.value);
    }

    fn evictLru(self: *Store) void {
        if (self.options.max_entries == 0) {
            self.clear();
            return;
        }
        while (self.entries.count() > self.options.max_entries) {
            var oldest_key: ?[]const u8 = null;
            var oldest_access: u64 = std.math.maxInt(u64);

            var it = self.entries.iterator();
            while (it.next()) |entry| {
                if (entry.value_ptr.last_access_ns < oldest_access) {
                    oldest_access = entry.value_ptr.last_access_ns;
                    oldest_key = entry.key_ptr.*;
                }
            }

            if (oldest_key) |key| {
                self.removeBorrowedKey(key);
            } else {
                break;
            }
        }
    }

    fn clear(self: *Store) void {
        var it = self.entries.iterator();
        while (it.next()) |entry| freeStored(self.allocator, entry.value_ptr.*);
        self.entries.clearRetainingCapacity();
    }

    fn isExpired(self: Store, module_id: []const u8, created_ns: u64, timestamp_ns: u64) bool {
        const ttl_ns = self.ttlNs(module_id);
        return ttl_ns != 0 and timestamp_ns >= created_ns and timestamp_ns - created_ns > ttl_ns;
    }

    fn ttlNs(self: Store, module_id: []const u8) u64 {
        for (self.options.module_ttls) |ttl| {
            if (std.mem.eql(u8, ttl.module_id, module_id)) return ttl.ttl_ns;
        }
        return self.options.default_ttl_ns;
    }
};

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

pub fn keyAlloc(allocator: std.mem.Allocator, input: KeyInput) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    const sorted_mtimes = try allocator.dupe(WatchedMtime, input.mtimes);
    defer allocator.free(sorted_mtimes);
    std.mem.sort(WatchedMtime, sorted_mtimes, {}, lessThanWatchedMtime);

    try appendString(allocator, &out, "module", input.module_id);
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

pub fn registerDeclaredWatches(watcher: *fsnotify.Watcher, module_id: []const u8, cwd: []const u8, paths: []const fsnotify.WatchPath, debounce_ms: u64) !void {
    try watcher.watch(.{
        .module_id = module_id,
        .cwd = cwd,
        .paths = paths,
        .debounce_ms = debounce_ms,
    });
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
    allocator.free(entry.module_id);
    allocator.free(entry.cwd);
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

test "module ttl expires command cache entries" {
    const module_ttls = [_]ModuleTtl{
        .{ .module_id = "language_versions", .ttl_ns = 10 },
        .{ .module_id = "git_branch", .ttl_ns = 100 },
    };
    var store = Store.initWithOptions(std.testing.allocator, .{
        .default_ttl_ns = 0,
        .module_ttls = module_ttls[0..],
    });
    defer store.deinit();

    const language_input = KeyInput{ .module_id = "language_versions", .cmd = "python3", .args = &.{"--version"}, .cwd = "/repo" };
    try store.putOutputAt(language_input, "Python 3.14", 100);
    try std.testing.expect((try store.getAt(language_input, 110)) != null);
    try std.testing.expect(try store.getAt(language_input, 111) == null);

    const git_input = KeyInput{ .module_id = "git_branch", .cmd = "git", .args = &.{ "status", "--short" }, .cwd = "/repo" };
    try store.putOutputAt(git_input, "clean", 100);
    try std.testing.expect((try store.getAt(git_input, 111)) != null);
}

test "zero ttl disables command cache expiry" {
    var store = Store.initWithOptions(std.testing.allocator, .{ .default_ttl_ns = 0 });
    defer store.deinit();

    const input = KeyInput{ .module_id = "tools", .cmd = "tool", .cwd = "/repo" };
    try store.putMissingToolAt(input, "tool", 1);
    try std.testing.expect((try store.getAt(input, 1_000_000)) != null);
}

test "fsnotify declared watch invalidates module cwd entries" {
    var watcher = fsnotify.Watcher.init(std.testing.allocator);
    defer watcher.deinit();
    const paths = [_]fsnotify.WatchPath{.{ .path = "/repo/package.json" }};
    try registerDeclaredWatches(&watcher, "language_versions", "/repo", paths[0..], fsnotify.default_debounce_ms);

    var store = Store.initWithOptions(std.testing.allocator, .{ .default_ttl_ns = 0 });
    defer store.deinit();
    const input = KeyInput{
        .module_id = "language_versions",
        .cmd = "node",
        .args = &.{"--version"},
        .cwd = "/repo",
        .mtimes = &.{.{ .path = "/repo/package.json", .mtime_ns = 1 }},
    };
    try store.putOutputAt(input, "v24.0.0", 1);
    try std.testing.expect((try store.getAt(input, 2)) != null);

    watcher.recordEvent("/repo/package.json", 1 * std.time.ns_per_ms);
    const invalidation = watcher.nextInvalidation(51 * std.time.ns_per_ms).?;
    try store.invalidateModuleCwd(invalidation.module_id, invalidation.cwd);
    try std.testing.expect(try store.getAt(input, 52 * std.time.ns_per_ms) == null);
}

test "thrash invalidation keeps command cache bounded" {
    var watcher = fsnotify.Watcher.init(std.testing.allocator);
    defer watcher.deinit();
    const paths = [_]fsnotify.WatchPath{.{ .path = "/repo/package.json" }};
    try registerDeclaredWatches(&watcher, "language_versions", "/repo", paths[0..], 0);

    var store = Store.initWithOptions(std.testing.allocator, .{ .default_ttl_ns = 0 });
    defer store.deinit();

    for (0..1000) |index| {
        const input = KeyInput{
            .module_id = "language_versions",
            .cmd = "node",
            .args = &.{"--version"},
            .cwd = "/repo",
            .mtimes = &.{.{ .path = "/repo/package.json", .mtime_ns = @intCast(index) }},
        };
        try store.putOutputAt(input, "v24.0.0", @intCast(index));
        watcher.recordEvent("/repo/package.json", @intCast(index));
        const invalidation = watcher.nextInvalidation(@intCast(index)).?;
        try store.invalidateModuleCwd(invalidation.module_id, invalidation.cwd);
        try std.testing.expectEqual(@as(usize, 0), store.count());
    }
}

test "high churn respects command cache memory ceiling" {
    var store = Store.initWithOptions(std.testing.allocator, .{ .max_entries = 128, .default_ttl_ns = 0 });
    defer store.deinit();

    for (0..5000) |index| {
        var arg_buffer: [32]u8 = undefined;
        const arg = try std.fmt.bufPrint(&arg_buffer, "probe-{d}", .{index});
        try store.putOutputAt(.{
            .module_id = "language_versions",
            .cmd = "probe",
            .args = &.{arg},
            .cwd = "/repo",
        }, "ok", @intCast(index));
    }

    try std.testing.expectEqual(@as(usize, 128), store.count());
    try std.testing.expect(try store.getAt(.{ .module_id = "language_versions", .cmd = "probe", .args = &.{"probe-0"}, .cwd = "/repo" }, 5001) == null);
    try std.testing.expect((try store.getAt(.{ .module_id = "language_versions", .cmd = "probe", .args = &.{"probe-4999"}, .cwd = "/repo" }, 5001)) != null);
}
