const std = @import("std");

pub const Entry = struct {
    output: []const u8,
    cache_rev: u64,
};

const StoredEntry = struct {
    key: []u8,
    output: []u8,
    cache_rev: u64,
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
        while (it.next()) |entry| {
            self.allocator.free(entry.value_ptr.key);
            self.allocator.free(entry.value_ptr.output);
        }
        self.entries.deinit();
        self.* = undefined;
    }

    pub fn put(self: *Store, module_id: []const u8, cwd: []const u8, output: []const u8, cache_rev: u64) !void {
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
        } else {
            entry.value_ptr.* = .{
                .key = key,
                .output = value,
                .cache_rev = cache_rev,
            };
        }
    }

    pub fn get(self: *Store, module_id: []const u8, cwd: []const u8) !?Entry {
        const key = try keyAlloc(self.allocator, module_id, cwd);
        defer self.allocator.free(key);
        const entry = self.entries.get(key) orelse return null;
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
};

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
