const std = @import("std");

pub const Entry = struct {
    output: []const u8,
    cache_rev: u64,
};

pub const Options = struct {
    max_entries: usize = 1024,
    max_age_ns: u64 = 5 * std.time.ns_per_min,
};

const StoredEntry = struct {
    key: []u8,
    output: []u8,
    cache_rev: u64,
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
        while (it.next()) |entry| {
            self.allocator.free(entry.value_ptr.key);
            self.allocator.free(entry.value_ptr.output);
        }
        self.entries.deinit();
        self.* = undefined;
    }

    pub fn put(self: *Store, module_id: []const u8, cwd: []const u8, output: []const u8, cache_rev: u64) !void {
        try self.putAt(module_id, cwd, output, cache_rev, nowNs());
    }

    pub fn putAt(self: *Store, module_id: []const u8, cwd: []const u8, output: []const u8, cache_rev: u64, timestamp_ns: u64) !void {
        const key = try keyAlloc(self.allocator, module_id, cwd);
        errdefer self.allocator.free(key);
        const value = try self.allocator.dupe(u8, output);
        errdefer self.allocator.free(value);

        const entry = try self.entries.getOrPut(key);
        if (entry.found_existing) {
            self.allocator.free(key);
            self.allocator.free(entry.value_ptr.output);
            entry.value_ptr.output = value;
            entry.value_ptr.cache_rev = cache_rev;
            entry.value_ptr.created_ns = timestamp_ns;
            entry.value_ptr.last_access_ns = timestamp_ns;
        } else {
            entry.value_ptr.* = .{
                .key = key,
                .output = value,
                .cache_rev = cache_rev,
                .created_ns = timestamp_ns,
                .last_access_ns = timestamp_ns,
            };
        }

        try self.evictExpired(timestamp_ns);
        self.evictLru();
    }

    pub fn get(self: *Store, module_id: []const u8, cwd: []const u8) !?Entry {
        return self.getAt(module_id, cwd, nowNs());
    }

    pub fn getAt(self: *Store, module_id: []const u8, cwd: []const u8, timestamp_ns: u64) !?Entry {
        const key = try keyAlloc(self.allocator, module_id, cwd);
        defer self.allocator.free(key);
        const entry = self.entries.getPtr(key) orelse return null;
        if (self.isExpired(entry.*, timestamp_ns)) {
            try self.invalidate(module_id, cwd);
            return null;
        }
        entry.last_access_ns = timestamp_ns;
        return .{
            .output = entry.output,
            .cache_rev = entry.cache_rev,
        };
    }

    pub fn invalidate(self: *Store, module_id: []const u8, cwd: []const u8) !void {
        const key = try keyAlloc(self.allocator, module_id, cwd);
        defer self.allocator.free(key);
        const removed = self.entries.fetchRemove(key) orelse return;
        self.allocator.free(removed.value.key);
        self.allocator.free(removed.value.output);
    }

    pub fn count(self: *Store) usize {
        return self.entries.count();
    }

    fn evictExpired(self: *Store, timestamp_ns: u64) !void {
        if (self.options.max_age_ns == 0) return;

        var expired: std.ArrayList([]u8) = .empty;
        defer {
            for (expired.items) |key| self.allocator.free(key);
            expired.deinit(self.allocator);
        }

        var it = self.entries.iterator();
        while (it.next()) |entry| {
            if (self.isExpired(entry.value_ptr.*, timestamp_ns)) {
                try expired.append(self.allocator, try self.allocator.dupe(u8, entry.key_ptr.*));
            }
        }

        for (expired.items) |key| {
            self.removeOwnedKey(key);
        }
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
        while (it.next()) |entry| {
            self.allocator.free(entry.value_ptr.key);
            self.allocator.free(entry.value_ptr.output);
        }
        self.entries.clearRetainingCapacity();
    }

    fn removeOwnedKey(self: *Store, key: []const u8) void {
        self.removeBorrowedKey(key);
    }

    fn removeBorrowedKey(self: *Store, key: []const u8) void {
        const removed = self.entries.fetchRemove(key) orelse return;
        self.allocator.free(removed.value.key);
        self.allocator.free(removed.value.output);
    }

    fn isExpired(self: Store, entry: StoredEntry, timestamp_ns: u64) bool {
        return self.options.max_age_ns != 0 and timestamp_ns >= entry.created_ns and timestamp_ns - entry.created_ns > self.options.max_age_ns;
    }
};

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

fn keyAlloc(allocator: std.mem.Allocator, module_id: []const u8, cwd: []const u8) ![]u8 {
    var key = try allocator.alloc(u8, module_id.len + 1 + cwd.len);
    @memcpy(key[0..module_id.len], module_id);
    key[module_id.len] = 0;
    @memcpy(key[module_id.len + 1 ..], cwd);
    return key;
}

test "stores entries by module and cwd" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    try store.put("git_branch", "/repo/a", "git:main", 1);
    try store.put("git_branch", "/repo/b", "git:dev", 2);
    try store.put("language_versions", "/repo/a", "lang:py:3.14", 3);

    const a_git = (try store.get("git_branch", "/repo/a")).?;
    try std.testing.expectEqualStrings("git:main", a_git.output);
    try std.testing.expectEqual(@as(u64, 1), a_git.cache_rev);

    const b_git = (try store.get("git_branch", "/repo/b")).?;
    try std.testing.expectEqualStrings("git:dev", b_git.output);

    const a_lang = (try store.get("language_versions", "/repo/a")).?;
    try std.testing.expectEqualStrings("lang:py:3.14", a_lang.output);
    try std.testing.expectEqual(@as(usize, 3), store.count());
}

test "replaces and invalidates entries" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    try store.put("git_branch", "/repo", "git:main", 1);
    try store.put("git_branch", "/repo", "git:main*", 2);

    const replaced = (try store.get("git_branch", "/repo")).?;
    try std.testing.expectEqualStrings("git:main*", replaced.output);
    try std.testing.expectEqual(@as(u64, 2), replaced.cache_rev);
    try std.testing.expectEqual(@as(usize, 1), store.count());

    try store.invalidate("git_branch", "/repo");
    try std.testing.expect(try store.get("git_branch", "/repo") == null);
    try std.testing.expectEqual(@as(usize, 0), store.count());
}

test "evicts least recently used entry above max entries" {
    var store = Store.initWithOptions(std.testing.allocator, .{ .max_entries = 2, .max_age_ns = 0 });
    defer store.deinit();

    try store.putAt("m", "/a", "a", 1, 10);
    try store.putAt("m", "/b", "b", 2, 20);
    _ = try store.getAt("m", "/a", 30);
    try store.putAt("m", "/c", "c", 3, 40);

    try std.testing.expect((try store.getAt("m", "/a", 50)) != null);
    try std.testing.expect(try store.getAt("m", "/b", 50) == null);
    try std.testing.expect((try store.getAt("m", "/c", 50)) != null);
    try std.testing.expectEqual(@as(usize, 2), store.count());
}

test "evicts entries older than max age" {
    var store = Store.initWithOptions(std.testing.allocator, .{ .max_entries = 16, .max_age_ns = 10 });
    defer store.deinit();

    try store.putAt("m", "/fresh", "fresh", 1, 100);
    try store.putAt("m", "/old", "old", 2, 101);

    try std.testing.expect((try store.getAt("m", "/fresh", 109)) != null);
    try std.testing.expect(try store.getAt("m", "/old", 112) == null);
}
