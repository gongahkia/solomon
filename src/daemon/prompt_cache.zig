const std = @import("std");
const cache = @import("cache.zig");

pub const Key = struct {
    cwd: []const u8,
    exit: i32,
    jobs: u32,
    duration_ms: u64,
    time: bool,
    no_async: bool,
    cache_rev: u64,
};

pub const Store = struct {
    backing: cache.Store,

    pub fn init(allocator: std.mem.Allocator) Store {
        return .{ .backing = cache.Store.init(allocator) };
    }

    pub fn deinit(self: *Store) void {
        self.backing.deinit();
    }

    pub fn put(self: *Store, key: Key, prompt: []const u8) !void {
        const encoded = try keyAlloc(self.backing.allocator, key);
        defer self.backing.allocator.free(encoded);
        try self.backing.put("rendered_prompt", encoded, prompt, key.cache_rev);
    }

    pub fn get(self: *Store, key: Key) !?[]const u8 {
        const encoded = try keyAlloc(self.backing.allocator, key);
        defer self.backing.allocator.free(encoded);
        const entry = try self.backing.get("rendered_prompt", encoded) orelse return null;
        return entry.output;
    }

    pub fn invalidate(self: *Store, key: Key) !void {
        const encoded = try keyAlloc(self.backing.allocator, key);
        defer self.backing.allocator.free(encoded);
        try self.backing.invalidate("rendered_prompt", encoded);
    }

    pub fn count(self: *Store) usize {
        return self.backing.count();
    }
};

fn keyAlloc(allocator: std.mem.Allocator, key: Key) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "{s}\x00{d}\x00{d}\x00{d}\x00{}\x00{}\x00{d}",
        .{ key.cwd, key.exit, key.jobs, key.duration_ms, key.time, key.no_async, key.cache_rev },
    );
}

test "memoizes prompt by cwd and state tuple" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    const key = Key{
        .cwd = "/repo",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 1200,
        .time = false,
        .no_async = false,
        .cache_rev = 7,
    };

    try store.put(key, "/repo jobs:1 took:1.2s> ");
    const prompt = (try store.get(key)).?;
    try std.testing.expectEqualStrings("/repo jobs:1 took:1.2s> ", prompt);
}

test "state changes produce different cache keys" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    const base = Key{
        .cwd = "/repo",
        .exit = 0,
        .jobs = 0,
        .duration_ms = 0,
        .time = false,
        .no_async = false,
        .cache_rev = 1,
    };
    try store.put(base, "/repo> ");

    var changed = base;
    changed.exit = 1;
    try std.testing.expect(try store.get(changed) == null);

    changed = base;
    changed.cache_rev = 2;
    try std.testing.expect(try store.get(changed) == null);
}
