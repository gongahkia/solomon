const std = @import("std");

pub const module_id = "vcs_worktree";

pub const Detection = struct {
    root_path: []u8,
    gitdir_path: []u8,
    name: []u8,

    pub fn deinit(self: *Detection, allocator: std.mem.Allocator) void {
        allocator.free(self.root_path);
        allocator.free(self.gitdir_path);
        allocator.free(self.name);
        self.* = undefined;
    }
};

pub fn detect(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_git = try std.fs.path.join(allocator, &.{ current, ".git" });
        const contents = std.fs.cwd().readFileAlloc(allocator, dot_git, 4096) catch |err| switch (err) {
            error.FileNotFound => {
                allocator.free(dot_git);
                if (!(try moveToParent(allocator, &current))) {
                    allocator.free(current);
                    return null;
                }
                continue;
            },
            error.IsDir => {
                allocator.free(dot_git);
                allocator.free(current);
                return null;
            },
            else => {
                allocator.free(dot_git);
                allocator.free(current);
                return err;
            },
        };
        defer allocator.free(contents);
        defer allocator.free(dot_git);

        const gitdir_path = parseGitdir(contents) orelse {
            allocator.free(current);
            return null;
        };
        if (!isLinkedWorktreeGitdir(gitdir_path)) {
            allocator.free(current);
            return null;
        }
        const name_source = nameFromRoot(current) orelse {
            allocator.free(current);
            return null;
        };

        const owned_gitdir = try allocator.dupe(u8, gitdir_path);
        errdefer allocator.free(owned_gitdir);
        const owned_name = try allocator.dupe(u8, name_source);
        return .{
            .root_path = current,
            .gitdir_path = owned_gitdir,
            .name = owned_name,
        };
    }

    allocator.free(current);
    return null;
}

pub fn renderAlloc(allocator: std.mem.Allocator, detection: Detection) ![]u8 {
    return std.fmt.allocPrint(allocator, "wt:{s}", .{detection.name});
}

pub fn parseGitdir(contents: []const u8) ?[]const u8 {
    const trimmed = std.mem.trim(u8, contents, " \t\r\n");
    const prefix = "gitdir:";
    if (!std.mem.startsWith(u8, trimmed, prefix)) return null;
    const path = std.mem.trim(u8, trimmed[prefix.len..], " \t\r\n");
    if (path.len == 0) return null;
    return path;
}

pub fn isLinkedWorktreeGitdir(gitdir_path: []const u8) bool {
    return std.mem.indexOf(u8, gitdir_path, ".git/worktrees/") != null or
        std.mem.indexOf(u8, gitdir_path, ".git\\worktrees\\") != null;
}

fn nameFromRoot(root_path: []const u8) ?[]const u8 {
    const trimmed = std.mem.trimRight(u8, root_path, "/\\");
    if (trimmed.len == 0) return null;
    const basename = std.fs.path.basename(trimmed);
    if (basename.len == 0) return null;
    return basename;
}

fn moveToParent(allocator: std.mem.Allocator, current: *[]u8) !bool {
    const parent = std.fs.path.dirname(current.*) orelse return false;
    if (std.mem.eql(u8, parent, current.*)) return false;
    const next = try allocator.dupe(u8, parent);
    allocator.free(current.*);
    current.* = next;
    return true;
}

fn runGit(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.testing.expect(switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    });
}

test "parses linked worktree gitdir" {
    try std.testing.expectEqualStrings("/repo/.git/worktrees/feature", parseGitdir("gitdir: /repo/.git/worktrees/feature\n").?);
    try std.testing.expect(isLinkedWorktreeGitdir("/repo/.git/worktrees/feature"));
    try std.testing.expect(!isLinkedWorktreeGitdir("/repo/.git/modules/submodule"));
}

test "ignores primary worktree" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-worktree-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    try std.testing.expect((try detect(allocator, dir_path)) == null);
}

test "detects linked worktree from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-worktree-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const tracked_path = try std.fmt.allocPrint(allocator, "{s}/tracked.txt", .{dir_path});
    defer allocator.free(tracked_path);
    var file = try std.fs.createFileAbsolute(tracked_path, .{});
    try file.writeAll("tracked");
    file.close();
    try runGit(allocator, dir_path, &.{ "git", "add", "tracked.txt" });
    try runGit(allocator, dir_path, &.{ "git", "-c", "user.name=shisa", "-c", "user.email=shisa@example.invalid", "commit", "-m", "init" });

    const linked_path = try std.fmt.allocPrint(allocator, "{s}-linked", .{dir_path});
    defer allocator.free(linked_path);
    defer std.fs.cwd().deleteTree(linked_path) catch {};
    try runGit(allocator, dir_path, &.{ "git", "worktree", "add", linked_path, "-b", "feature" });

    const nested_path = try std.fmt.allocPrint(allocator, "{s}/a/b", .{linked_path});
    defer allocator.free(nested_path);
    try std.fs.cwd().makePath(nested_path);

    var detection = (try detect(allocator, nested_path)).?;
    defer detection.deinit(allocator);
    const expected_name = std.fs.path.basename(linked_path);
    try std.testing.expectEqualStrings(linked_path, detection.root_path);
    try std.testing.expectEqualStrings(expected_name, detection.name);
    try std.testing.expect(std.mem.indexOf(u8, detection.gitdir_path, ".git/worktrees/") != null);

    const rendered = try renderAlloc(allocator, detection);
    defer allocator.free(rendered);
    const expected = try std.fmt.allocPrint(allocator, "wt:{s}", .{expected_name});
    defer allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered);
}
