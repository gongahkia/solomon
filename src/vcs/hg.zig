const std = @import("std");

pub const module_id = "hg_state";

pub const Summary = struct {
    parent: []u8,
    description: []u8,
    branch: []u8,
    commit: []u8,
    update: []u8,
    phases: []u8,

    pub fn deinit(self: *Summary, allocator: std.mem.Allocator) void {
        allocator.free(self.parent);
        allocator.free(self.description);
        allocator.free(self.branch);
        allocator.free(self.commit);
        allocator.free(self.update);
        allocator.free(self.phases);
        self.* = undefined;
    }

    pub fn clone(self: Summary, allocator: std.mem.Allocator) !Summary {
        const parent = try allocator.dupe(u8, self.parent);
        errdefer allocator.free(parent);
        const description = try allocator.dupe(u8, self.description);
        errdefer allocator.free(description);
        const branch = try allocator.dupe(u8, self.branch);
        errdefer allocator.free(branch);
        const commit = try allocator.dupe(u8, self.commit);
        errdefer allocator.free(commit);
        const update = try allocator.dupe(u8, self.update);
        errdefer allocator.free(update);
        const phases = try allocator.dupe(u8, self.phases);
        return .{
            .parent = parent,
            .description = description,
            .branch = branch,
            .commit = commit,
            .update = update,
            .phases = phases,
        };
    }
};

pub const RefSummary = struct {
    branch: []u8,
    active_bookmark: []u8,
    topic: []u8,
    phase: []u8,

    pub fn deinit(self: *RefSummary, allocator: std.mem.Allocator) void {
        allocator.free(self.branch);
        allocator.free(self.active_bookmark);
        allocator.free(self.topic);
        allocator.free(self.phase);
        self.* = undefined;
    }
};

pub const Cache = struct {
    valid: bool = false,
    root_path: ?[]u8 = null,
    summary: ?Summary = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.clear(allocator);
    }

    pub fn invalidate(self: *Cache, allocator: std.mem.Allocator, root_path: []const u8) void {
        if (self.root_path == null or !std.mem.eql(u8, self.root_path.?, root_path)) return;
        self.clear(allocator);
    }

    pub fn read(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !?Summary {
        const root = (try findRoot(allocator, cwd_path)) orelse return null;
        defer allocator.free(root);

        if (self.valid and self.root_path != null and std.mem.eql(u8, self.root_path.?, root)) {
            if (self.summary) |summary| return try summary.clone(allocator);
            return null;
        }

        self.clear(allocator);
        self.root_path = try allocator.dupe(u8, root);
        self.valid = true;
        self.summary = try readSummary(allocator, cwd_path);
        if (self.summary) |summary| return try summary.clone(allocator);
        return null;
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.root_path) |value| allocator.free(value);
        if (self.summary) |*summary| summary.deinit(allocator);
        self.valid = false;
        self.root_path = null;
        self.summary = null;
    }
};

pub fn findRoot(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_hg = try std.fs.path.join(allocator, &.{ current, ".hg" });
        const found = found: {
            std.fs.cwd().access(dot_hg, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(dot_hg);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(dot_hg);
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

pub fn readSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?Summary {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "hg", "summary", "--remote" },
        .cwd = cwd_path,
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return parseSummary(allocator, result.stdout);
}

pub fn readRefSummary(allocator: std.mem.Allocator, cwd_path: []const u8) !?RefSummary {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "hg", "log", "-r", ".", "--template", "{branch}\\n{activebookmark}\\n{phase}\\n{join(extras, \"\\n\")}\\n" },
        .cwd = cwd_path,
        .max_output_bytes = 16 * 1024,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    return parseRefSummary(allocator, result.stdout);
}

pub fn parseSummary(allocator: std.mem.Allocator, output: []const u8) !?Summary {
    var parent: []const u8 = "";
    var description: []const u8 = "";
    var branch: []const u8 = "";
    var commit: []const u8 = "";
    var update: []const u8 = "";
    var phases: []const u8 = "";

    var lines = std.mem.splitScalar(u8, output, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trimRight(u8, raw_line, "\r");
        if (line.len == 0) continue;
        if (std.mem.startsWith(u8, line, "parent:")) {
            parent = std.mem.trim(u8, line["parent:".len..], " \t");
        } else if (std.mem.startsWith(u8, line, "branch:")) {
            branch = std.mem.trim(u8, line["branch:".len..], " \t");
        } else if (std.mem.startsWith(u8, line, "commit:")) {
            commit = std.mem.trim(u8, line["commit:".len..], " \t");
        } else if (std.mem.startsWith(u8, line, "update:")) {
            update = std.mem.trim(u8, line["update:".len..], " \t");
        } else if (std.mem.startsWith(u8, line, "phases:")) {
            phases = std.mem.trim(u8, line["phases:".len..], " \t");
        } else if (line[0] == ' ' and description.len == 0) {
            description = std.mem.trim(u8, line, " \t");
        }
    }
    if (parent.len == 0 and branch.len == 0 and commit.len == 0 and phases.len == 0) return null;

    const owned_parent = try allocator.dupe(u8, parent);
    errdefer allocator.free(owned_parent);
    const owned_description = try allocator.dupe(u8, description);
    errdefer allocator.free(owned_description);
    const owned_branch = try allocator.dupe(u8, branch);
    errdefer allocator.free(owned_branch);
    const owned_commit = try allocator.dupe(u8, commit);
    errdefer allocator.free(owned_commit);
    const owned_update = try allocator.dupe(u8, update);
    errdefer allocator.free(owned_update);
    const owned_phases = try allocator.dupe(u8, phases);
    return .{
        .parent = owned_parent,
        .description = owned_description,
        .branch = owned_branch,
        .commit = owned_commit,
        .update = owned_update,
        .phases = owned_phases,
    };
}

pub fn parseRefSummary(allocator: std.mem.Allocator, output: []const u8) !?RefSummary {
    var lines = std.mem.splitScalar(u8, output, '\n');
    const branch = std.mem.trim(u8, lines.next() orelse return null, " \t\r");
    const active_bookmark = std.mem.trim(u8, lines.next() orelse "", " \t\r");
    const phase = std.mem.trim(u8, lines.next() orelse "", " \t\r");
    var topic: []const u8 = "";
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (std.mem.startsWith(u8, line, "topic=")) {
            topic = std.mem.trim(u8, line["topic=".len..], " \t");
            break;
        }
    }
    if (branch.len == 0 and active_bookmark.len == 0 and topic.len == 0 and phase.len == 0) return null;

    const rendered_branch = if (branch.len == 0) "default" else branch;
    const owned_branch = try allocator.dupe(u8, rendered_branch);
    errdefer allocator.free(owned_branch);
    const owned_active_bookmark = try allocator.dupe(u8, active_bookmark);
    errdefer allocator.free(owned_active_bookmark);
    const owned_topic = try allocator.dupe(u8, topic);
    errdefer allocator.free(owned_topic);
    const owned_phase = try allocator.dupe(u8, phase);
    return .{
        .branch = owned_branch,
        .active_bookmark = owned_active_bookmark,
        .topic = owned_topic,
        .phase = owned_phase,
    };
}

pub fn formatRefSummaryAlloc(allocator: std.mem.Allocator, summary: RefSummary) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try std.fmt.format(out.writer(allocator), "hg:branch:{s}", .{summary.branch});
    if (summary.active_bookmark.len > 0) try std.fmt.format(out.writer(allocator), " bm:{s}", .{summary.active_bookmark});
    if (summary.topic.len > 0) try std.fmt.format(out.writer(allocator), " topic:{s}", .{summary.topic});
    if (summary.phase.len > 0) try std.fmt.format(out.writer(allocator), " phase:{s}", .{summary.phase});
    return try out.toOwnedSlice(allocator);
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "detects hg repo in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-hg-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_hg = try std.fmt.allocPrint(allocator, "{s}/.hg", .{dir_path});
    defer allocator.free(dot_hg);
    try std.fs.cwd().makePath(dot_hg);

    const root = (try findRoot(allocator, dir_path)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
    try std.testing.expect(try isRepo(allocator, dir_path));
}

test "detects hg repo from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-hg-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const dot_hg = try std.fmt.allocPrint(allocator, "{s}/.hg", .{dir_path});
    defer allocator.free(dot_hg);
    try std.fs.cwd().makePath(dot_hg);

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    const root = (try findRoot(allocator, nested)).?;
    defer allocator.free(root);
    try std.testing.expectEqualStrings(dir_path, root);
}

test "ignores non hg directories" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-hg-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect(!(try isRepo(allocator, dir_path)));
    try std.testing.expect((try findRoot(allocator, dir_path)) == null);
}

test "parses hg summary output" {
    const output =
        \\parent: 0:f666183f198a tip
        \\ first
        \\branch: default
        \\commit: 1 modified, 1 unknown
        \\update: (current)
        \\phases: 1 draft
        \\
    ;
    var summary = (try parseSummary(std.testing.allocator, output)).?;
    defer summary.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("0:f666183f198a tip", summary.parent);
    try std.testing.expectEqualStrings("first", summary.description);
    try std.testing.expectEqualStrings("default", summary.branch);
    try std.testing.expectEqualStrings("1 modified, 1 unknown", summary.commit);
    try std.testing.expectEqualStrings("(current)", summary.update);
    try std.testing.expectEqualStrings("1 draft", summary.phases);
}

test "parses hg ref summary output" {
    const output =
        \\default
        \\feature
        \\draft
        \\branch=default
        \\topic=stack
        \\
    ;
    var summary = (try parseRefSummary(std.testing.allocator, output)).?;
    defer summary.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("default", summary.branch);
    try std.testing.expectEqualStrings("feature", summary.active_bookmark);
    try std.testing.expectEqualStrings("stack", summary.topic);
    try std.testing.expectEqualStrings("draft", summary.phase);
}

test "formats hg ref summary" {
    var summary = RefSummary{
        .branch = try std.testing.allocator.dupe(u8, "default"),
        .active_bookmark = try std.testing.allocator.dupe(u8, "feature"),
        .topic = try std.testing.allocator.dupe(u8, "stack"),
        .phase = try std.testing.allocator.dupe(u8, "draft"),
    };
    defer summary.deinit(std.testing.allocator);

    const rendered = try formatRefSummaryAlloc(std.testing.allocator, summary);
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("hg:branch:default bm:feature topic:stack phase:draft", rendered);
}

test "hg summary cache invalidates by root" {
    const allocator = std.testing.allocator;
    var cache = Cache{
        .valid = true,
        .root_path = try allocator.dupe(u8, "/repo"),
        .summary = (try parseSummary(allocator,
            \\parent: 0:f666183f198a tip
            \\ first
            \\branch: default
            \\commit: clean
            \\update: (current)
            \\phases: 1 draft
            \\
        )).?,
    };
    defer cache.deinit(allocator);

    cache.invalidate(allocator, "/other");
    try std.testing.expect(cache.valid);
    cache.invalidate(allocator, "/repo");
    try std.testing.expect(!cache.valid);
}

test "reads real hg summary when hg is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-hg-real-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "init" })) return error.SkipZigTest;
    const file_path = try std.fmt.allocPrint(allocator, "{s}/f.txt", .{dir_path});
    defer allocator.free(file_path);
    try writeFile(file_path, "one\n");
    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "add", "f.txt" })) return error.SkipZigTest;
    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "commit", "-m", "first", "-u", "Bench <bench@example.test>" })) return error.SkipZigTest;

    var summary = (try readSummary(allocator, dir_path)) orelse return error.SkipZigTest;
    defer summary.deinit(allocator);
    try std.testing.expectEqualStrings("default", summary.branch);
    try std.testing.expect(std.mem.indexOf(u8, summary.parent, "tip") != null);
}

test "reads real hg ref summary when hg is installed" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-hg-ref-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "init" })) return error.SkipZigTest;
    const file_path = try std.fmt.allocPrint(allocator, "{s}/f.txt", .{dir_path});
    defer allocator.free(file_path);
    try writeFile(file_path, "one\n");
    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "add", "f.txt" })) return error.SkipZigTest;
    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "commit", "-m", "first", "-u", "Bench <bench@example.test>" })) return error.SkipZigTest;
    if (!try runCommandOk(allocator, dir_path, &.{ "hg", "bookmark", "feature" })) return error.SkipZigTest;

    var summary = (try readRefSummary(allocator, dir_path)) orelse return error.SkipZigTest;
    defer summary.deinit(allocator);
    try std.testing.expectEqualStrings("default", summary.branch);
    try std.testing.expectEqualStrings("feature", summary.active_bookmark);
    try std.testing.expectEqualStrings("draft", summary.phase);
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
