const std = @import("std");

pub const module_id = "jj_op_log";

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

pub const OperationSummary = struct {
    id: []u8,
    description: []u8,

    pub fn deinit(self: *OperationSummary, allocator: std.mem.Allocator) void {
        allocator.free(self.id);
        allocator.free(self.description);
        self.* = undefined;
    }
};

pub const ChangeSummary = struct {
    change_id: []u8,
    commit_id: []u8,
    description: []u8,
    divergent: bool,

    pub fn deinit(self: *ChangeSummary, allocator: std.mem.Allocator) void {
        allocator.free(self.change_id);
        allocator.free(self.commit_id);
        allocator.free(self.description);
        self.* = undefined;
    }
};

pub const Cache = struct {
    valid: bool = false,
    root_path: ?[]u8 = null,
    segment: ?[]u8 = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn invalidate(self: *Cache, allocator: std.mem.Allocator, root_path: []const u8) void {
        if (self.root_path == null or !std.mem.eql(u8, self.root_path.?, root_path)) return;
        self.clear(allocator);
    }

    pub fn render(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
        const root = (try findRoot(allocator, cwd_path)) orelse return null;
        defer allocator.free(root);

        if (self.valid and self.root_path != null and std.mem.eql(u8, self.root_path.?, root)) {
            if (self.segment) |segment| return try allocator.dupe(u8, segment);
            return null;
        }

        self.clear(allocator);
        self.root_path = try allocator.dupe(u8, root);
        self.valid = true;
        self.segment = try renderOperationSummary(allocator, cwd_path);
        if (self.segment) |segment| return try allocator.dupe(u8, segment);
        return null;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.root_path) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.valid = false;
        self.root_path = null;
        self.segment = null;
    }
};

pub const WatchScope = struct {
    cwd: []u8,
    root_path: []u8,
    op_heads_path: []u8,
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
        allocator.free(self.op_heads_path);
        self.* = undefined;
    }
};

pub fn findRoot(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_jj = try std.fs.path.join(allocator, &.{ current, ".jj" });
        const found = found: {
            std.fs.cwd().access(dot_jj, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(dot_jj);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(dot_jj);
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
    const op_heads_path = try std.fs.path.join(allocator, &.{ root, ".jj", "repo", "op_heads" });
    errdefer allocator.free(op_heads_path);

    return .{
        .cwd = cwd,
        .root_path = root,
        .op_heads_path = op_heads_path,
        .paths = .{.{ .path = op_heads_path, .recursive = true }},
    };
}

pub fn readOperationSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?OperationSummary {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "jj", "op", "log", "--no-graph" },
        .cwd = cwd_path,
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseLatestOperation(allocator, result.stdout);
}

pub fn renderOperationSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var operation = (try readOperationSummary(allocator, cwd_path)) orelse return null;
    defer operation.deinit(allocator);
    const short_id = operation.id[0..@min(operation.id.len, 8)];
    return std.fmt.allocPrint(allocator, "jj:op:{s} {s}", .{ short_id, operation.description });
}

pub fn readChangeSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?ChangeSummary {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{
            "jj",
            "log",
            "--no-graph",
            "-r",
            "@",
            "--color",
            "never",
            "-T",
            "change_id.short(8) ++ \"\\n\" ++ commit_id.short(8) ++ \"\\n\" ++ coalesce(description.first_line(), \"(no description set)\") ++ \"\\n\" ++ if(divergent, \"divergent\", \"\") ++ \"\\n\"",
        },
        .cwd = cwd_path,
        .max_output_bytes = 16 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseChangeSummary(allocator, result.stdout);
}

pub fn renderChangeSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var summary = (try readChangeSummary(allocator, cwd_path)) orelse return null;
    defer summary.deinit(allocator);
    return formatChangeSummaryAlloc(allocator, summary);
}

pub fn parseLatestOperation(allocator: std.mem.Allocator, output: []const u8) !?OperationSummary {
    var lines = std.mem.tokenizeScalar(u8, output, '\n');
    const header = lines.next() orelse return null;
    const description_line = lines.next() orelse return null;

    var header_tokens = std.mem.tokenizeAny(u8, header, " \t\r");
    const id = header_tokens.next() orelse return null;
    const description = std.mem.trim(u8, description_line, " \t\r");
    if (id.len == 0 or description.len == 0) return null;

    const owned_id = try allocator.dupe(u8, id);
    errdefer allocator.free(owned_id);
    const owned_description = try allocator.dupe(u8, description);
    return .{
        .id = owned_id,
        .description = owned_description,
    };
}

pub fn parseChangeSummary(allocator: std.mem.Allocator, output: []const u8) !?ChangeSummary {
    var lines = std.mem.splitScalar(u8, output, '\n');
    const change_id = std.mem.trim(u8, lines.next() orelse return null, " \t\r");
    const commit_id = std.mem.trim(u8, lines.next() orelse return null, " \t\r");
    const description = std.mem.trim(u8, lines.next() orelse return null, " \t\r");
    const divergence = std.mem.trim(u8, lines.next() orelse "", " \t\r");
    if (change_id.len == 0 or commit_id.len == 0) return null;

    const rendered_description = if (description.len == 0) "(no description set)" else description;
    const owned_change_id = try allocator.dupe(u8, change_id);
    errdefer allocator.free(owned_change_id);
    const owned_commit_id = try allocator.dupe(u8, commit_id);
    errdefer allocator.free(owned_commit_id);
    const owned_description = try allocator.dupe(u8, rendered_description);
    return .{
        .change_id = owned_change_id,
        .commit_id = owned_commit_id,
        .description = owned_description,
        .divergent = std.mem.eql(u8, divergence, "divergent"),
    };
}

pub fn formatChangeSummaryAlloc(allocator: std.mem.Allocator, summary: ChangeSummary) ![]u8 {
    const short_change_id = summary.change_id[0..@min(summary.change_id.len, 8)];
    if (summary.divergent) {
        return std.fmt.allocPrint(allocator, "jj:{s} {s} divergent", .{ short_change_id, summary.description });
    }
    return std.fmt.allocPrint(allocator, "jj:{s} {s}", .{ short_change_id, summary.description });
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "detects jj repo in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_jj = try std.fmt.allocPrint(allocator, "{s}/.jj", .{dir_path});
    defer allocator.free(dot_jj);
    try std.fs.cwd().makePath(dot_jj);

    const root = (try findRoot(allocator, dir_path)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
    try std.testing.expect(try isRepo(allocator, dir_path));
}

test "detects jj repo from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_jj = try std.fmt.allocPrint(allocator, "{s}/.jj", .{dir_path});
    defer allocator.free(dot_jj);
    try std.fs.cwd().makePath(dot_jj);

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    const root = (try findRoot(allocator, nested)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
}

test "ignores non jj directories" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect(!(try isRepo(allocator, dir_path)));
    try std.testing.expect((try findRoot(allocator, dir_path)) == null);
}

test "watch scope tracks jj op heads" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_jj = try std.fmt.allocPrint(allocator, "{s}/.jj/repo/op_heads", .{dir_path});
    defer allocator.free(dot_jj);
    try std.fs.cwd().makePath(dot_jj);

    var watched = (try watchScope(allocator, dir_path)).?;
    defer watched.deinit(allocator);

    const expected = try std.fmt.allocPrint(allocator, "{s}/.jj/repo/op_heads", .{dir_path});
    defer allocator.free(expected);
    try std.testing.expectEqualStrings(module_id, watched.scope().module_id);
    try std.testing.expectEqualStrings(dir_path, watched.scope().cwd);
    try std.testing.expectEqualStrings(expected, watched.paths[0].path);
    try std.testing.expect(watched.paths[0].recursive);
}

test "parses latest jj operation" {
    const output =
        \\6f57871f668d user@example.test now, lasted 20 milliseconds
        \\add workspace 'default'
        \\000000000000 root()
        \\
    ;
    var operation = (try parseLatestOperation(std.testing.allocator, output)).?;
    defer operation.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("6f57871f668d", operation.id);
    try std.testing.expectEqualStrings("add workspace 'default'", operation.description);
}

test "formats jj operation summary" {
    const output =
        \\abcdef123456 user@example.test now, lasted 1 millisecond
        \\snapshot working copy
        \\
    ;
    var operation = (try parseLatestOperation(std.testing.allocator, output)).?;
    defer operation.deinit(std.testing.allocator);
    const rendered = try std.fmt.allocPrint(std.testing.allocator, "jj:op:{s} {s}", .{ operation.id[0..8], operation.description });
    defer std.testing.allocator.free(rendered);

    try std.testing.expectEqualStrings("jj:op:abcdef12 snapshot working copy", rendered);
}

test "parses current jj change summary" {
    const output =
        \\yztrvqqq
        \\1234abcd
        \\working desc
        \\divergent
        \\
    ;
    var summary = (try parseChangeSummary(std.testing.allocator, output)).?;
    defer summary.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("yztrvqqq", summary.change_id);
    try std.testing.expectEqualStrings("1234abcd", summary.commit_id);
    try std.testing.expectEqualStrings("working desc", summary.description);
    try std.testing.expect(summary.divergent);
}

test "formats current jj change summary" {
    var summary = ChangeSummary{
        .change_id = try std.testing.allocator.dupe(u8, "yztrvqqqxxxx"),
        .commit_id = try std.testing.allocator.dupe(u8, "1234abcd"),
        .description = try std.testing.allocator.dupe(u8, "working desc"),
        .divergent = false,
    };
    defer summary.deinit(std.testing.allocator);

    const rendered = try formatChangeSummaryAlloc(std.testing.allocator, summary);
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("jj:yztrvqqq working desc", rendered);
}

test "defaults empty jj change description" {
    const output =
        \\yztrvqqq
        \\1234abcd
        \\
        \\
    ;
    var summary = (try parseChangeSummary(std.testing.allocator, output)).?;
    defer summary.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("(no description set)", summary.description);
    try std.testing.expect(!summary.divergent);
}

test "cache invalidates by jj root" {
    const allocator = std.testing.allocator;
    var cache = Cache{
        .valid = true,
        .root_path = try allocator.dupe(u8, "/repo"),
        .segment = try allocator.dupe(u8, "jj:op:abcdef12 snapshot"),
    };
    defer cache.deinit(allocator);

    cache.invalidate(allocator, "/other");
    try std.testing.expect(cache.valid);
    cache.invalidate(allocator, "/repo");
    try std.testing.expect(!cache.valid);
}

test "reads real jj op log when jj is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-real-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const init = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "jj", "git", "init" },
        .cwd = dir_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return error.SkipZigTest;
    defer allocator.free(init.stdout);
    defer allocator.free(init.stderr);
    if (!exitedZero(init.term)) return error.SkipZigTest;

    var operation = (try readOperationSummary(allocator, dir_path)) orelse return error.SkipZigTest;
    defer operation.deinit(allocator);
    try std.testing.expect(operation.id.len >= 8);
    try std.testing.expect(std.mem.indexOf(u8, operation.description, "workspace") != null);
}

test "reads real jj current change when jj is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-jj-change-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const init = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "jj", "git", "init" },
        .cwd = dir_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return error.SkipZigTest;
    defer allocator.free(init.stdout);
    defer allocator.free(init.stderr);
    if (!exitedZero(init.term)) return error.SkipZigTest;

    const describe = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "jj", "describe", "-m", "working desc" },
        .cwd = dir_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return error.SkipZigTest;
    defer allocator.free(describe.stdout);
    defer allocator.free(describe.stderr);
    if (!exitedZero(describe.term)) return error.SkipZigTest;

    var summary = (try readChangeSummary(allocator, dir_path)) orelse return error.SkipZigTest;
    defer summary.deinit(allocator);
    try std.testing.expect(summary.change_id.len >= 8);
    try std.testing.expect(summary.commit_id.len >= 8);
    try std.testing.expectEqualStrings("working desc", summary.description);
}
