const std = @import("std");

const legacy_persist_magic = "SHISA-CACHE\n";
const persist_magic = "SHISA-CACHE\x00";
const persist_schema_version: u32 = 2;
const checksum_seed: u64 = 0x51_48_49_53_41;
const max_persisted_entries = 1_000_000;
const max_persisted_bytes = 64 * 1024 * 1024;
const max_persisted_slice = 16 * 1024 * 1024;

pub const Entry = struct {
    output: []const u8,
    cache_rev: u64,
};

pub const Options = struct {
    max_entries: usize = 1024,
    max_age_ns: u64 = 5 * std.time.ns_per_min,
    /// optional path written by `shisa pin`. Entries whose pin scope matches a
    /// listed path are retained across normal TTL and LRU eviction.
    pin_path: ?[]const u8 = null,
};

const StoredEntry = struct {
    key: []u8,
    pin_scope: ?[]u8,
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
            if (entry.value_ptr.pin_scope) |scope| self.allocator.free(scope);
            self.allocator.free(entry.value_ptr.output);
        }
        self.entries.deinit();
        self.* = undefined;
    }

    pub fn put(self: *Store, module_id: []const u8, cwd: []const u8, output: []const u8, cache_rev: u64) !void {
        try self.putAtScoped(module_id, cwd, cwd, output, cache_rev, nowNs());
    }

    pub fn putAt(self: *Store, module_id: []const u8, cwd: []const u8, output: []const u8, cache_rev: u64, timestamp_ns: u64) !void {
        try self.putAtScoped(module_id, cwd, cwd, output, cache_rev, timestamp_ns);
    }

    pub fn putScoped(self: *Store, module_id: []const u8, key_scope: []const u8, pin_scope: []const u8, output: []const u8, cache_rev: u64) !void {
        try self.putAtScoped(module_id, key_scope, pin_scope, output, cache_rev, nowNs());
    }

    pub fn putAtScoped(self: *Store, module_id: []const u8, key_scope: []const u8, pin_scope: []const u8, output: []const u8, cache_rev: u64, timestamp_ns: u64) !void {
        const key = try keyAlloc(self.allocator, module_id, key_scope);
        errdefer self.allocator.free(key);
        const owned_pin_scope = try self.allocator.dupe(u8, pin_scope);
        errdefer self.allocator.free(owned_pin_scope);
        const value = try self.allocator.dupe(u8, output);
        errdefer self.allocator.free(value);

        const entry = try self.entries.getOrPut(key);
        if (entry.found_existing) {
            self.allocator.free(key);
            if (entry.value_ptr.pin_scope) |previous_scope| self.allocator.free(previous_scope);
            self.allocator.free(entry.value_ptr.output);
            entry.value_ptr.pin_scope = owned_pin_scope;
            entry.value_ptr.output = value;
            entry.value_ptr.cache_rev = cache_rev;
            entry.value_ptr.created_ns = timestamp_ns;
            entry.value_ptr.last_access_ns = timestamp_ns;
        } else {
            entry.value_ptr.* = .{
                .key = key,
                .pin_scope = owned_pin_scope,
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
            if (self.isPinned(entry.*)) {
                entry.last_access_ns = timestamp_ns;
                return .{
                    .output = entry.output,
                    .cache_rev = entry.cache_rev,
                };
            }
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
        if (removed.value.pin_scope) |scope| self.allocator.free(scope);
        self.allocator.free(removed.value.output);
    }

    pub fn invalidateModule(self: *Store, module_id: []const u8) !void {
        var remove_keys: std.ArrayList([]u8) = .empty;
        defer {
            for (remove_keys.items) |key| self.allocator.free(key);
            remove_keys.deinit(self.allocator);
        }

        var it = self.entries.iterator();
        while (it.next()) |entry| {
            if (keyMatchesModule(entry.key_ptr.*, module_id)) {
                try remove_keys.append(self.allocator, try self.allocator.dupe(u8, entry.key_ptr.*));
            }
        }

        for (remove_keys.items) |key| self.removeBorrowedKey(key);
    }

    pub fn count(self: *Store) usize {
        return self.entries.count();
    }

    pub fn saveToFile(self: *Store, path: []const u8) !void {
        var payload: std.ArrayList(u8) = .empty;
        defer payload.deinit(self.allocator);
        try self.writeEntriesToBytes(&payload);

        var bytes: std.ArrayList(u8) = .empty;
        defer bytes.deinit(self.allocator);
        try bytes.appendSlice(self.allocator, persist_magic);
        try appendU32(self.allocator, &bytes, persist_schema_version);
        try appendU64(self.allocator, &bytes, cacheChecksum(payload.items));
        try bytes.appendSlice(self.allocator, payload.items);
        try self.writeBytesToFile(path, bytes.items);
    }

    fn writeEntriesToBytes(self: *Store, bytes: *std.ArrayList(u8)) !void {
        try appendU32(self.allocator, bytes, try checkedU32(self.entries.count()));
        var it = self.entries.iterator();
        while (it.next()) |entry| {
            try appendU32(self.allocator, bytes, try checkedU32(entry.key_ptr.*.len));
            try appendU32(self.allocator, bytes, try checkedU32(entry.value_ptr.output.len));
            try appendU64(self.allocator, bytes, entry.value_ptr.cache_rev);
            try appendU64(self.allocator, bytes, entry.value_ptr.created_ns);
            try appendU64(self.allocator, bytes, entry.value_ptr.last_access_ns);
            try bytes.appendSlice(self.allocator, entry.key_ptr.*);
            try bytes.appendSlice(self.allocator, entry.value_ptr.output);
        }
    }

    fn writeBytesToFile(self: *Store, path: []const u8, bytes: []const u8) !void {
        _ = self;
        if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
        var file = if (std.fs.path.isAbsolute(path))
            try std.fs.createFileAbsolute(path, .{ .truncate = true })
        else
            try std.fs.cwd().createFile(path, .{ .truncate = true });
        defer file.close();
        try file.writeAll(bytes);
    }

    pub fn loadFromFile(self: *Store, path: []const u8) !void {
        const contents = std.fs.cwd().readFileAlloc(self.allocator, path, max_persisted_bytes) catch |err| switch (err) {
            error.FileNotFound => return,
            else => return err,
        };
        defer self.allocator.free(contents);
        try self.loadFromBytes(contents);
    }

    fn loadFromBytes(self: *Store, contents: []const u8) !void {
        var input = contents;
        if (consumePrefix(&input, persist_magic)) {
            const schema_version = try readU32(&input);
            if (schema_version == 2) {
                const expected_checksum = try readU64(&input);
                if (cacheChecksum(input) != expected_checksum) return error.CacheChecksumMismatch;
                try self.loadEntriesFromBytes(input);
                return;
            }
            if (schema_version == 1) {
                try self.loadEntriesFromBytes(input);
                return;
            }
            return error.UnsupportedCacheSchema;
        }
        if (consumePrefix(&input, legacy_persist_magic)) {
            try self.loadEntriesFromBytes(input);
            return;
        }
        return error.InvalidCacheFile;
    }

    fn loadEntriesFromBytes(self: *Store, source: []const u8) !void {
        var input = source;
        const entry_count = try readU32(&input);
        if (entry_count > max_persisted_entries) return error.InvalidCacheFile;

        var loaded = Store.initWithOptions(self.allocator, self.options);
        errdefer loaded.deinit();
        for (0..entry_count) |_| {
            const key_len = try readU32(&input);
            const output_len = try readU32(&input);
            if (key_len > max_persisted_slice or output_len > max_persisted_slice) return error.InvalidCacheFile;
            const cache_rev = try readU64(&input);
            const created_ns = try readU64(&input);
            const last_access_ns = try readU64(&input);
            const key = try readSlice(&input, key_len);
            const output = try readSlice(&input, output_len);
            try loaded.putEncodedAt(key, output, cache_rev, created_ns, last_access_ns);
        }
        if (input.len != 0) return error.InvalidCacheFile;
        try loaded.evictExpired(nowNs());
        loaded.evictLru();

        self.clear();
        self.entries.deinit();
        self.entries = loaded.entries;
        loaded.entries = std.StringHashMap(StoredEntry).init(self.allocator);
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
            if (self.isExpired(entry.value_ptr.*, timestamp_ns) and !self.isPinned(entry.value_ptr.*)) {
                try expired.append(self.allocator, try self.allocator.dupe(u8, entry.key_ptr.*));
            }
        }

        for (expired.items) |key| {
            self.removeOwnedKey(key);
        }
    }

    fn evictLru(self: *Store) void {
        while (self.entries.count() > self.options.max_entries) {
            var oldest_key: ?[]const u8 = null;
            var oldest_access: u64 = std.math.maxInt(u64);

            var it = self.entries.iterator();
            while (it.next()) |entry| {
                if (self.isPinned(entry.value_ptr.*)) continue;
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

    pub fn clear(self: *Store) void {
        var it = self.entries.iterator();
        while (it.next()) |entry| {
            self.allocator.free(entry.value_ptr.key);
            if (entry.value_ptr.pin_scope) |scope| self.allocator.free(scope);
            self.allocator.free(entry.value_ptr.output);
        }
        self.entries.clearRetainingCapacity();
    }

    fn putEncodedAt(self: *Store, key_source: []const u8, output_source: []const u8, cache_rev: u64, created_ns: u64, last_access_ns: u64) !void {
        const key = try self.allocator.dupe(u8, key_source);
        errdefer self.allocator.free(key);
        const output = try self.allocator.dupe(u8, output_source);
        errdefer self.allocator.free(output);

        const entry = try self.entries.getOrPut(key);
        if (entry.found_existing) {
            self.allocator.free(key);
            self.allocator.free(entry.value_ptr.output);
            if (entry.value_ptr.pin_scope) |scope| self.allocator.free(scope);
            entry.value_ptr.pin_scope = null;
            entry.value_ptr.output = output;
            entry.value_ptr.cache_rev = cache_rev;
            entry.value_ptr.created_ns = created_ns;
            entry.value_ptr.last_access_ns = last_access_ns;
        } else {
            entry.value_ptr.* = .{
                .key = key,
                .pin_scope = null,
                .output = output,
                .cache_rev = cache_rev,
                .created_ns = created_ns,
                .last_access_ns = last_access_ns,
            };
        }
    }

    fn removeOwnedKey(self: *Store, key: []const u8) void {
        self.removeBorrowedKey(key);
    }

    fn removeBorrowedKey(self: *Store, key: []const u8) void {
        const removed = self.entries.fetchRemove(key) orelse return;
        self.allocator.free(removed.value.key);
        if (removed.value.pin_scope) |scope| self.allocator.free(scope);
        self.allocator.free(removed.value.output);
    }

    fn isPinned(self: *Store, entry: StoredEntry) bool {
        const scope = entry.pin_scope orelse return false;
        const pin_path = self.options.pin_path orelse return false;
        const contents = std.fs.cwd().readFileAlloc(self.allocator, pin_path, 1024 * 1024) catch |err| switch (err) {
            error.FileNotFound => return false,
            // retain entries if pin state cannot be read. dropping a pin due to
            // a transient permission or I/O failure would violate its contract.
            else => return true,
        };
        defer self.allocator.free(contents);

        var lines = std.mem.tokenizeScalar(u8, contents, '\n');
        while (lines.next()) |line| {
            const pinned_path = std.mem.trim(u8, line, " \t\r");
            if (scopeMatchesPin(scope, pinned_path)) return true;
        }
        return false;
    }

    fn isExpired(self: Store, entry: StoredEntry, timestamp_ns: u64) bool {
        return self.options.max_age_ns != 0 and timestamp_ns >= entry.created_ns and timestamp_ns - entry.created_ns > self.options.max_age_ns;
    }
};

fn scopeMatchesPin(scope: []const u8, pinned_path: []const u8) bool {
    if (pinned_path.len == 0 or !std.mem.startsWith(u8, scope, pinned_path)) return false;
    if (scope.len == pinned_path.len) return true;
    const last = pinned_path[pinned_path.len - 1];
    if (last == '/' or last == '\\') return true;
    const next = scope[pinned_path.len];
    return next == '/' or next == '\\';
}

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

pub fn defaultPersistPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/cache.bin", .{home_path}));
}

fn keyAlloc(allocator: std.mem.Allocator, module_id: []const u8, cwd: []const u8) ![]u8 {
    var key = try allocator.alloc(u8, module_id.len + 1 + cwd.len);
    @memcpy(key[0..module_id.len], module_id);
    key[module_id.len] = 0;
    @memcpy(key[module_id.len + 1 ..], cwd);
    return key;
}

fn keyMatchesModule(key: []const u8, module_id: []const u8) bool {
    return key.len > module_id.len and std.mem.startsWith(u8, key, module_id) and key[module_id.len] == 0;
}

fn checkedU32(value: usize) !u32 {
    return std.math.cast(u32, value) orelse error.CacheFileTooLarge;
}

fn cacheChecksum(bytes: []const u8) u64 {
    return std.hash.Wyhash.hash(checksum_seed, bytes);
}

fn appendU32(allocator: std.mem.Allocator, out: *std.ArrayList(u8), value: u32) !void {
    var buffer: [4]u8 = undefined;
    std.mem.writeInt(u32, buffer[0..], value, .big);
    try out.appendSlice(allocator, buffer[0..]);
}

fn appendU64(allocator: std.mem.Allocator, out: *std.ArrayList(u8), value: u64) !void {
    var buffer: [8]u8 = undefined;
    std.mem.writeInt(u64, buffer[0..], value, .big);
    try out.appendSlice(allocator, buffer[0..]);
}

fn consumePrefix(input: *[]const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, input.*, prefix)) return false;
    input.* = input.*[prefix.len..];
    return true;
}

fn readU32(input: *[]const u8) !u32 {
    if (input.*.len < 4) return error.InvalidCacheFile;
    const value = std.mem.readInt(u32, input.*[0..4], .big);
    input.* = input.*[4..];
    return value;
}

fn readU64(input: *[]const u8) !u64 {
    if (input.*.len < 8) return error.InvalidCacheFile;
    const value = std.mem.readInt(u64, input.*[0..8], .big);
    input.* = input.*[8..];
    return value;
}

fn readSlice(input: *[]const u8, len: usize) ![]const u8 {
    if (input.*.len < len) return error.InvalidCacheFile;
    const value = input.*[0..len];
    input.* = input.*[len..];
    return value;
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

test "invalidates all entries for one module" {
    var store = Store.init(std.testing.allocator);
    defer store.deinit();

    try store.put("git_branch", "/repo/a", "git:main", 1);
    try store.put("git_branch", "/repo/b", "git:dev", 2);
    try store.put("language_versions", "/repo/a", "py:3.14", 3);

    try store.invalidateModule("git_branch");
    try std.testing.expect(try store.get("git_branch", "/repo/a") == null);
    try std.testing.expect(try store.get("git_branch", "/repo/b") == null);
    try std.testing.expect((try store.get("language_versions", "/repo/a")) != null);
    try std.testing.expectEqual(@as(usize, 1), store.count());
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

test "retains pinned scopes across lru and ttl eviction" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-pins-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const pins_path = try std.fmt.allocPrint(allocator, "{s}/pins", .{dir_path});
    defer allocator.free(pins_path);
    try std.fs.cwd().writeFile(.{ .sub_path = pins_path, .data = "/repo\n" });

    var store = Store.initWithOptions(allocator, .{
        .max_entries = 2,
        .max_age_ns = 10,
        .pin_path = pins_path,
    });
    defer store.deinit();
    try store.putAt("m", "/repo/subdir", "pinned", 1, 100);
    try store.putAt("m", "/old", "old", 2, 105);
    try store.putAt("m", "/fresh", "fresh", 3, 109);

    try std.testing.expect((try store.getAt("m", "/repo/subdir", 109)) != null);
    try std.testing.expect(try store.getAt("m", "/old", 109) == null);
    try std.testing.expect((try store.getAt("m", "/fresh", 109)) != null);

    try store.putAt("m", "/later", "later", 4, 120);
    try std.testing.expect((try store.getAt("m", "/repo/subdir", 120)) != null);
    try std.testing.expect(try store.getAt("m", "/fresh", 120) == null);
    try std.testing.expect((try store.getAt("m", "/later", 120)) != null);
}

test "property cache eviction invariants" {
    const allocator = std.testing.allocator;
    var prng = std.Random.DefaultPrng.init(0x434143484549);
    const random = prng.random();

    for (0..64) |_| {
        const max_entries = random.intRangeAtMost(usize, 0, 8);
        const max_age_ns = random.intRangeAtMost(u64, 0, 40);
        var store = Store.initWithOptions(allocator, .{ .max_entries = max_entries, .max_age_ns = max_age_ns });
        defer store.deinit();

        var now: u64 = 0;
        for (0..64) |step| {
            now += random.intRangeAtMost(u64, 1, 5);
            const module_id = try std.fmt.allocPrint(allocator, "m{d}", .{random.intRangeAtMost(u8, 0, 3)});
            defer allocator.free(module_id);
            const cwd = try std.fmt.allocPrint(allocator, "/repo/{d}", .{random.intRangeAtMost(u8, 0, 12)});
            defer allocator.free(cwd);
            const output = try std.fmt.allocPrint(allocator, "out-{d}", .{step});
            defer allocator.free(output);

            try store.putAt(module_id, cwd, output, step, now);
            try expectEvictionInvariants(&store, now);

            if (random.boolean()) {
                _ = try store.getAt(module_id, cwd, now);
                try std.testing.expect(store.count() <= store.options.max_entries);
            }
        }
    }
}

fn expectEvictionInvariants(store: *Store, timestamp_ns: u64) !void {
    try std.testing.expect(store.count() <= store.options.max_entries);
    if (store.options.max_age_ns == 0) return;
    var it = store.entries.iterator();
    while (it.next()) |entry| {
        try std.testing.expect(!store.isExpired(entry.value_ptr.*, timestamp_ns));
    }
}

test "builds default persistent cache path" {
    const path = (try defaultPersistPathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/cache.bin", path);
    try std.testing.expect(try defaultPersistPathAlloc(std.testing.allocator, null) == null);
}

test "persists optional module cache to cache bin" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const path = try std.fmt.allocPrint(allocator, "{s}/cache.bin", .{dir_path});
    defer allocator.free(path);

    var store = Store.initWithOptions(allocator, .{ .max_entries = 16, .max_age_ns = 0 });
    defer store.deinit();
    try store.putAt("git_branch", "/repo", "git:main", 7, 100);
    try store.putAt("language_versions", "/repo", "py:3.14", 8, 110);
    try store.saveToFile(path);

    var loaded = Store.initWithOptions(allocator, .{ .max_entries = 16, .max_age_ns = 0 });
    defer loaded.deinit();
    try loaded.loadFromFile(path);

    const git = (try loaded.getAt("git_branch", "/repo", 120)).?;
    try std.testing.expectEqualStrings("git:main", git.output);
    try std.testing.expectEqual(@as(u64, 7), git.cache_rev);
    const lang = (try loaded.getAt("language_versions", "/repo", 120)).?;
    try std.testing.expectEqualStrings("py:3.14", lang.output);
    try std.testing.expectEqual(@as(usize, 2), loaded.count());
}

test "loads legacy unversioned persistent cache as migration" {
    const allocator = std.testing.allocator;
    const key = try keyAlloc(allocator, "git_branch", "/repo");
    defer allocator.free(key);

    var bytes: std.ArrayList(u8) = .empty;
    defer bytes.deinit(allocator);
    try bytes.appendSlice(allocator, legacy_persist_magic);
    try appendU32(allocator, &bytes, 1);
    try appendU32(allocator, &bytes, try checkedU32(key.len));
    try appendU32(allocator, &bytes, 8);
    try appendU64(allocator, &bytes, 9);
    try appendU64(allocator, &bytes, 100);
    try appendU64(allocator, &bytes, 100);
    try bytes.appendSlice(allocator, key);
    try bytes.appendSlice(allocator, "git:main");

    var store = Store.initWithOptions(allocator, .{ .max_entries = 16, .max_age_ns = 0 });
    defer store.deinit();
    try store.loadFromBytes(bytes.items);

    const git = (try store.getAt("git_branch", "/repo", 120)).?;
    try std.testing.expectEqualStrings("git:main", git.output);
    try std.testing.expectEqual(@as(u64, 9), git.cache_rev);
}

test "loads v1 persistent cache as migration" {
    const allocator = std.testing.allocator;
    const key = try keyAlloc(allocator, "language_versions", "/repo");
    defer allocator.free(key);

    var bytes: std.ArrayList(u8) = .empty;
    defer bytes.deinit(allocator);
    try bytes.appendSlice(allocator, persist_magic);
    try appendU32(allocator, &bytes, 1);
    try appendU32(allocator, &bytes, 1);
    try appendU32(allocator, &bytes, try checkedU32(key.len));
    try appendU32(allocator, &bytes, 7);
    try appendU64(allocator, &bytes, 10);
    try appendU64(allocator, &bytes, 100);
    try appendU64(allocator, &bytes, 100);
    try bytes.appendSlice(allocator, key);
    try bytes.appendSlice(allocator, "py:3.14");

    var store = Store.initWithOptions(allocator, .{ .max_entries = 16, .max_age_ns = 0 });
    defer store.deinit();
    try store.loadFromBytes(bytes.items);

    const lang = (try store.getAt("language_versions", "/repo", 120)).?;
    try std.testing.expectEqualStrings("py:3.14", lang.output);
    try std.testing.expectEqual(@as(u64, 10), lang.cache_rev);
}

test "rejects persistent cache checksum mismatch" {
    const allocator = std.testing.allocator;
    var payload: std.ArrayList(u8) = .empty;
    defer payload.deinit(allocator);
    try appendU32(allocator, &payload, 0);

    var bytes: std.ArrayList(u8) = .empty;
    defer bytes.deinit(allocator);
    try bytes.appendSlice(allocator, persist_magic);
    try appendU32(allocator, &bytes, persist_schema_version);
    try appendU64(allocator, &bytes, cacheChecksum(payload.items) + 1);
    try bytes.appendSlice(allocator, payload.items);

    var store = Store.init(allocator);
    defer store.deinit();
    try std.testing.expectError(error.CacheChecksumMismatch, store.loadFromBytes(bytes.items));
}

test "rejects unsupported persistent cache schema" {
    const allocator = std.testing.allocator;
    var bytes: std.ArrayList(u8) = .empty;
    defer bytes.deinit(allocator);
    try bytes.appendSlice(allocator, persist_magic);
    try appendU32(allocator, &bytes, 999);
    try appendU32(allocator, &bytes, 0);

    var store = Store.init(allocator);
    defer store.deinit();
    try std.testing.expectError(error.UnsupportedCacheSchema, store.loadFromBytes(bytes.items));
}

test "missing persistent cache file is optional" {
    const missing = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-missing-cache-{x}.bin", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(missing);
    var store = Store.init(std.testing.allocator);
    defer store.deinit();
    try store.loadFromFile(missing);
    try std.testing.expectEqual(@as(usize, 0), store.count());
}
