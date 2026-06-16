const std = @import("std");

pub const module_id = "sl_state";

pub const WatchPath = struct {
    path: []const u8,
    recursive: bool = false,
};

pub const Scope = struct {
    module_id: []const u8,
    cwd: []const u8,
    paths: []const WatchPath,
    debounce_ms: u64 = 50,
};

pub const StatusSummary = struct {
    modified: u32 = 0,
    added: u32 = 0,
    removed: u32 = 0,
    deleted: u32 = 0,
    unknown: u32 = 0,
    ignored: u32 = 0,
    clean: u32 = 0,

    pub fn total(self: StatusSummary) u32 {
        return self.modified + self.added + self.removed + self.deleted + self.unknown + self.ignored + self.clean;
    }
};

pub const Cache = struct {
    valid: bool = false,
    root_path: ?[]u8 = null,
    summary: ?StatusSummary = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn invalidate(self: *Cache, allocator: std.mem.Allocator, root_path: []const u8) void {
        if (self.root_path == null or !std.mem.eql(u8, self.root_path.?, root_path)) return;
        self.clear(allocator);
    }

    pub fn read(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !?StatusSummary {
        const root = (try findRoot(allocator, cwd_path)) orelse return null;
        defer allocator.free(root);

        if (self.valid and self.root_path != null and std.mem.eql(u8, self.root_path.?, root)) return self.summary;

        self.clear(allocator);
        self.root_path = try allocator.dupe(u8, root);
        self.valid = true;
        self.summary = try readStatusSummary(allocator, cwd_path);
        return self.summary;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.root_path) |value| allocator.free(value);
        self.valid = false;
        self.root_path = null;
        self.summary = null;
    }
};

pub const WatchScope = struct {
    cwd: []u8,
    root_path: []u8,
    store_path: []u8,
    paths: [1]WatchPath,

    pub fn scope(self: *const WatchScope) Scope {
        return .{
            .module_id = module_id,
            .cwd = self.cwd,
            .paths = self.paths[0..],
            .debounce_ms = 50,
        };
    }

    pub fn deinit(self: *WatchScope, allocator: std.mem.Allocator) void {
        allocator.free(self.cwd);
        allocator.free(self.root_path);
        allocator.free(self.store_path);
        self.* = undefined;
    }
};

pub fn findRoot(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_sl = try std.fs.path.join(allocator, &.{ current, ".sl" });
        const found = found: {
            std.fs.cwd().access(dot_sl, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(dot_sl);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(dot_sl);
        if (found) return current;

        const parent = std.fs.path.dirname(current) orelse {
            allocator.free(current);
            break;
        };
        if (std.mem.eql(u8, parent, current)) {
            allocator.free(current);
            break;
        }
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }

    return null;
}

pub fn isRepo(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const root = try findRoot(allocator, cwd_path);
    if (root) |path| {
        allocator.free(path);
        return true;
    }
    return false;
}

pub fn watchScope(allocator: std.mem.Allocator, cwd_path: []const u8) !?WatchScope {
    const root = (try findRoot(allocator, cwd_path)) orelse return null;
    errdefer allocator.free(root);
    const cwd = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(cwd);
    const store_path = try std.fs.path.join(allocator, &.{ root, ".sl", "store" });
    errdefer allocator.free(store_path);

    return .{
        .cwd = cwd,
        .root_path = root,
        .store_path = store_path,
        .paths = .{.{ .path = store_path, .recursive = true }},
    };
}

pub fn readStatusSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?StatusSummary {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "sl", "status", "--root-relative" },
        .cwd = cwd_path,
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseStatusSummary(result.stdout);
}

pub fn parseStatusSummary(output: []const u8) StatusSummary {
    var summary = StatusSummary{};
    var lines = std.mem.splitScalar(u8, output, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trimRight(u8, raw_line, "\r");
        if (line.len == 0) continue;
        switch (line[0]) {
            'M' => summary.modified += 1,
            'A' => summary.added += 1,
            'R' => summary.removed += 1,
            '!' => summary.deleted += 1,
            '?' => summary.unknown += 1,
            'I' => summary.ignored += 1,
            'C' => summary.clean += 1,
            else => {},
        }
    }
    return summary;
}

pub fn formatStatusSummaryAlloc(allocator: std.mem.Allocator, summary: StatusSummary) !?[]u8 {
    if (summary.total() == 0) return null;

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator, "sl:");
    var wrote = false;
    try appendStatusPart(allocator, &out, &wrote, "M", summary.modified);
    try appendStatusPart(allocator, &out, &wrote, "A", summary.added);
    try appendStatusPart(allocator, &out, &wrote, "R", summary.removed);
    try appendStatusPart(allocator, &out, &wrote, "!", summary.deleted);
    try appendStatusPart(allocator, &out, &wrote, "?", summary.unknown);
    try appendStatusPart(allocator, &out, &wrote, "I", summary.ignored);
    try appendStatusPart(allocator, &out, &wrote, "C", summary.clean);
    return try out.toOwnedSlice(allocator);
}

fn appendStatusPart(allocator: std.mem.Allocator, out: *std.ArrayList(u8), wrote: *bool, label: []const u8, count: u32) !void {
    if (count == 0) return;
    if (wrote.*) try out.append(allocator, ',');
    wrote.* = true;
    try std.fmt.format(out.writer(allocator), "{s}{d}", .{ label, count });
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "detects sapling repo in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_sl = try std.fmt.allocPrint(allocator, "{s}/.sl", .{dir_path});
    defer allocator.free(dot_sl);
    try std.fs.cwd().makePath(dot_sl);

    const root = (try findRoot(allocator, dir_path)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
    try std.testing.expect(try isRepo(allocator, dir_path));
}

test "detects sapling repo from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_sl = try std.fmt.allocPrint(allocator, "{s}/.sl", .{dir_path});
    defer allocator.free(dot_sl);
    try std.fs.cwd().makePath(dot_sl);

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    const root = (try findRoot(allocator, nested)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
}

test "ignores non sapling directories" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect(!(try isRepo(allocator, dir_path)));
    try std.testing.expect((try findRoot(allocator, dir_path)) == null);
}

test "watch scope tracks sapling store" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const store = try std.fmt.allocPrint(allocator, "{s}/.sl/store", .{dir_path});
    defer allocator.free(store);
    try std.fs.cwd().makePath(store);

    var watched = (try watchScope(allocator, dir_path)).?;
    defer watched.deinit(allocator);

    try std.testing.expectEqualStrings(module_id, watched.scope().module_id);
    try std.testing.expectEqualStrings(dir_path, watched.scope().cwd);
    try std.testing.expectEqualStrings(store, watched.paths[0].path);
    try std.testing.expect(watched.paths[0].recursive);
}

test "parses sapling status output" {
    const output =
        \\M modified.txt
        \\A added.txt
        \\R removed.txt
        \\! deleted.txt
        \\? unknown.txt
        \\I ignored.txt
        \\
    ;
    const summary = parseStatusSummary(output);
    try std.testing.expectEqual(@as(u32, 1), summary.modified);
    try std.testing.expectEqual(@as(u32, 1), summary.added);
    try std.testing.expectEqual(@as(u32, 1), summary.removed);
    try std.testing.expectEqual(@as(u32, 1), summary.deleted);
    try std.testing.expectEqual(@as(u32, 1), summary.unknown);
    try std.testing.expectEqual(@as(u32, 1), summary.ignored);
}

test "formats sapling status summary" {
    const summary = StatusSummary{
        .modified = 2,
        .added = 1,
        .unknown = 3,
    };
    const rendered = (try formatStatusSummaryAlloc(std.testing.allocator, summary)).?;
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("sl:M2,A1,?3", rendered);
}

test "sapling status cache invalidates by root" {
    const allocator = std.testing.allocator;
    var cache = Cache{
        .valid = true,
        .root_path = try allocator.dupe(u8, "/repo"),
        .summary = .{ .modified = 1 },
    };
    defer cache.deinit(allocator);

    cache.invalidate(allocator, "/other");
    try std.testing.expect(cache.valid);
    cache.invalidate(allocator, "/repo");
    try std.testing.expect(!cache.valid);
}

test "reads real sapling status when sl is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-real-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const init = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "sl", "init" },
        .cwd = dir_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return error.SkipZigTest;
    defer allocator.free(init.stdout);
    defer allocator.free(init.stderr);
    if (!exitedZero(init.term)) return error.SkipZigTest;

    const unknown_path = try std.fmt.allocPrint(allocator, "{s}/unknown.txt", .{dir_path});
    defer allocator.free(unknown_path);
    var file = try std.fs.createFileAbsolute(unknown_path, .{});
    try file.writeAll("unknown");
    file.close();

    const summary = (try readStatusSummary(allocator, dir_path)) orelse return error.SkipZigTest;
    try std.testing.expectEqual(@as(u32, 1), summary.unknown);
}
