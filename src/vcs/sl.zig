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

pub const SmartlogPosition = struct {
    node: []u8,
    description: []u8,
    index: u32,
    total: u32,

    pub fn deinit(self: *SmartlogPosition, allocator: std.mem.Allocator) void {
        allocator.free(self.node);
        allocator.free(self.description);
        self.* = undefined;
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

pub fn readSmartlogPosition(allocator: std.mem.Allocator, cwd_path: []const u8) !?SmartlogPosition {
    const current = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "sl", "log", "-r", ".", "--template", "{node|short}\n{desc|firstline}\n" },
        .cwd = cwd_path,
        .max_output_bytes = 16 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(current.stdout);
    defer allocator.free(current.stderr);
    if (!exitedZero(current.term)) return null;

    const stack = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "sl", "log", "-r", "::. - public()", "--template", "{node|short}\n" },
        .cwd = cwd_path,
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(stack.stdout);
    defer allocator.free(stack.stderr);
    if (!exitedZero(stack.term)) return null;

    return parseSmartlogPosition(allocator, current.stdout, stack.stdout);
}

pub fn parseSmartlogPosition(allocator: std.mem.Allocator, current_output: []const u8, stack_output: []const u8) !?SmartlogPosition {
    var current_lines = std.mem.splitScalar(u8, current_output, '\n');
    const node = std.mem.trim(u8, current_lines.next() orelse return null, " \t\r");
    const description = std.mem.trim(u8, current_lines.next() orelse "", " \t\r");
    if (node.len == 0) return null;

    var stack_lines = std.mem.splitScalar(u8, stack_output, '\n');
    var total: u32 = 0;
    var index: u32 = 0;
    while (stack_lines.next()) |raw_line| {
        const stack_node = std.mem.trim(u8, raw_line, " \t\r");
        if (stack_node.len == 0) continue;
        total += 1;
        if (std.mem.eql(u8, stack_node, node)) index = total;
    }
    if (index == 0 or total == 0) return null;

    const owned_node = try allocator.dupe(u8, node);
    errdefer allocator.free(owned_node);
    const rendered_description = if (description.len == 0) "(no description)" else description;
    const owned_description = try allocator.dupe(u8, rendered_description);
    return .{
        .node = owned_node,
        .description = owned_description,
        .index = index,
        .total = total,
    };
}

pub fn formatSmartlogPositionAlloc(allocator: std.mem.Allocator, position: SmartlogPosition) ![]u8 {
    return std.fmt.allocPrint(allocator, "sl:stack:{d}/{d} {s} {s}", .{ position.index, position.total, position.node, position.description });
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

test "parses sapling smartlog position" {
    const current =
        \\bbbb2222
        \\second
        \\
    ;
    const stack =
        \\aaaa1111
        \\bbbb2222
        \\
    ;
    var position = (try parseSmartlogPosition(std.testing.allocator, current, stack)).?;
    defer position.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("bbbb2222", position.node);
    try std.testing.expectEqualStrings("second", position.description);
    try std.testing.expectEqual(@as(u32, 2), position.index);
    try std.testing.expectEqual(@as(u32, 2), position.total);
}

test "formats sapling smartlog position" {
    var position = SmartlogPosition{
        .node = try std.testing.allocator.dupe(u8, "bbbb2222"),
        .description = try std.testing.allocator.dupe(u8, "second"),
        .index = 2,
        .total = 3,
    };
    defer position.deinit(std.testing.allocator);

    const rendered = try formatSmartlogPositionAlloc(std.testing.allocator, position);
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("sl:stack:2/3 bbbb2222 second", rendered);
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

test "reads real sapling smartlog position when sl is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-sl-smartlog-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    if (!try runCommandOk(allocator, dir_path, &.{ "sl", "init" })) return error.SkipZigTest;
    if (!try runCommandOk(allocator, dir_path, &.{ "sl", "config", "--local", "ui.username", "Bench <bench@example.test>" })) return error.SkipZigTest;

    const file_path = try std.fmt.allocPrint(allocator, "{s}/f.txt", .{dir_path});
    defer allocator.free(file_path);
    try writeFile(file_path, "one\n");
    if (!try runCommandOk(allocator, dir_path, &.{ "sl", "add", "f.txt" })) return error.SkipZigTest;
    if (!try runCommandOk(allocator, dir_path, &.{ "sl", "commit", "-m", "first" })) return error.SkipZigTest;
    try writeFile(file_path, "two\n");
    if (!try runCommandOk(allocator, dir_path, &.{ "sl", "commit", "-m", "second" })) return error.SkipZigTest;

    var position = (try readSmartlogPosition(allocator, dir_path)) orelse return error.SkipZigTest;
    defer position.deinit(allocator);
    try std.testing.expectEqual(@as(u32, 2), position.index);
    try std.testing.expectEqual(@as(u32, 2), position.total);
    try std.testing.expectEqualStrings("second", position.description);
}

fn runCommandOk(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) !bool {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return false;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return exitedZero(result.term);
}

fn writeFile(path: []const u8, contents: []const u8) !void {
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(contents);
}
