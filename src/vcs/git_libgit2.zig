const std = @import("std");
const builtin = @import("builtin");
const git_state = @import("git_state.zig");

const GitRepository = opaque {};
const GitReference = opaque {};
const GitTree = opaque {};
const GitStatusList = opaque {};
const GitOid = extern struct { id: [20]u8 };

const GitStrArray = extern struct {
    strings: [*c][*c]u8 = null,
    count: usize = 0,
};

const GitStatusOptions = extern struct {
    version: c_uint = git_status_options_version,
    show: c_int = git_status_show_index_and_workdir,
    flags: c_uint = git_status_opt_include_untracked | git_status_opt_recurse_untracked_dirs,
    pathspec: GitStrArray = .{},
    baseline: ?*GitTree = null,
    rename_threshold: c_ushort = 50,
};

const git_status_options_version: c_uint = 1;
const git_status_show_index_and_workdir: c_int = 0;
const git_status_index_new: c_uint = 1 << 0;
const git_status_index_modified: c_uint = 1 << 1;
const git_status_index_deleted: c_uint = 1 << 2;
const git_status_index_renamed: c_uint = 1 << 3;
const git_status_index_typechange: c_uint = 1 << 4;
const git_status_wt_new: c_uint = 1 << 7;
const git_status_wt_modified: c_uint = 1 << 8;
const git_status_wt_deleted: c_uint = 1 << 9;
const git_status_wt_typechange: c_uint = 1 << 10;
const git_status_wt_renamed: c_uint = 1 << 11;
const git_status_wt_unreadable: c_uint = 1 << 12;
const git_status_conflicted: c_uint = 1 << 15;
const git_status_opt_include_untracked: c_uint = 1 << 0;
const git_status_opt_recurse_untracked_dirs: c_uint = 1 << 4;

pub const Snapshot = struct {
    branch: ?[]u8 = null,
    counts: git_state.WorktreeCounts = .{},
    ahead_behind: ?git_state.AheadBehind = null,
    detached: bool = false,

    pub fn deinit(self: *Snapshot, allocator: std.mem.Allocator) void {
        if (self.branch) |branch| allocator.free(branch);
        self.* = .{};
    }
};

const Runtime = struct {
    lib: std.DynLib,
    git_libgit2_init: *const fn () callconv(.c) c_int,
    git_libgit2_shutdown: *const fn () callconv(.c) c_int,
    git_repository_open_ext: *const fn (**GitRepository, [*:0]const u8, c_uint, ?[*:0]const u8) callconv(.c) c_int,
    git_repository_free: *const fn (*GitRepository) callconv(.c) void,
    git_repository_head: *const fn (**GitReference, *GitRepository) callconv(.c) c_int,
    git_repository_head_detached: *const fn (*GitRepository) callconv(.c) c_int,
    git_reference_free: *const fn (*GitReference) callconv(.c) void,
    git_reference_target: *const fn (*const GitReference) callconv(.c) ?*const GitOid,
    git_branch_name: *const fn (*[*:0]const u8, *const GitReference) callconv(.c) c_int,
    git_branch_upstream: *const fn (**GitReference, *const GitReference) callconv(.c) c_int,
    git_graph_ahead_behind: *const fn (*usize, *usize, *GitRepository, *const GitOid, *const GitOid) callconv(.c) c_int,
    git_status_options_init: *const fn (*GitStatusOptions, c_uint) callconv(.c) c_int,
    git_status_foreach_ext: *const fn (*GitRepository, *const GitStatusOptions, StatusCallback, ?*anyopaque) callconv(.c) c_int,

    const StatusCallback = *const fn ([*c]const u8, c_uint, ?*anyopaque) callconv(.c) c_int;

    fn open() !Runtime {
        var lib = try openLibrary();
        errdefer lib.close();
        var runtime = Runtime{
            .lib = lib,
            .git_libgit2_init = try lookup(&lib, *const fn () callconv(.c) c_int, "git_libgit2_init"),
            .git_libgit2_shutdown = try lookup(&lib, *const fn () callconv(.c) c_int, "git_libgit2_shutdown"),
            .git_repository_open_ext = try lookup(&lib, *const fn (**GitRepository, [*:0]const u8, c_uint, ?[*:0]const u8) callconv(.c) c_int, "git_repository_open_ext"),
            .git_repository_free = try lookup(&lib, *const fn (*GitRepository) callconv(.c) void, "git_repository_free"),
            .git_repository_head = try lookup(&lib, *const fn (**GitReference, *GitRepository) callconv(.c) c_int, "git_repository_head"),
            .git_repository_head_detached = try lookup(&lib, *const fn (*GitRepository) callconv(.c) c_int, "git_repository_head_detached"),
            .git_reference_free = try lookup(&lib, *const fn (*GitReference) callconv(.c) void, "git_reference_free"),
            .git_reference_target = try lookup(&lib, *const fn (*const GitReference) callconv(.c) ?*const GitOid, "git_reference_target"),
            .git_branch_name = try lookup(&lib, *const fn (*[*:0]const u8, *const GitReference) callconv(.c) c_int, "git_branch_name"),
            .git_branch_upstream = try lookup(&lib, *const fn (**GitReference, *const GitReference) callconv(.c) c_int, "git_branch_upstream"),
            .git_graph_ahead_behind = try lookup(&lib, *const fn (*usize, *usize, *GitRepository, *const GitOid, *const GitOid) callconv(.c) c_int, "git_graph_ahead_behind"),
            .git_status_options_init = try lookup(&lib, *const fn (*GitStatusOptions, c_uint) callconv(.c) c_int, "git_status_options_init"),
            .git_status_foreach_ext = try lookup(&lib, *const fn (*GitRepository, *const GitStatusOptions, StatusCallback, ?*anyopaque) callconv(.c) c_int, "git_status_foreach_ext"),
        };
        if (runtime.git_libgit2_init() < 0) return error.Libgit2InitFailed;
        return runtime;
    }

    fn close(self: *Runtime) void {
        _ = self.git_libgit2_shutdown();
        self.lib.close();
    }
};

pub fn available() bool {
    var runtime = Runtime.open() catch return false;
    runtime.close();
    return true;
}

pub fn readSnapshot(allocator: std.mem.Allocator, cwd_path: []const u8) !?Snapshot {
    var runtime = Runtime.open() catch return null;
    defer runtime.close();

    const cwd_z = try allocator.dupeZ(u8, cwd_path);
    defer allocator.free(cwd_z);

    var repo: *GitRepository = undefined;
    if (runtime.git_repository_open_ext(&repo, cwd_z.ptr, 0, null) < 0) return null;
    defer runtime.git_repository_free(repo);

    var snapshot = Snapshot{ .detached = runtime.git_repository_head_detached(repo) == 1 };
    errdefer snapshot.deinit(allocator);

    var head: *GitReference = undefined;
    if (runtime.git_repository_head(&head, repo) == 0) {
        defer runtime.git_reference_free(head);
        var branch_name: [*:0]const u8 = undefined;
        if (runtime.git_branch_name(&branch_name, head) == 0) {
            snapshot.branch = try allocator.dupe(u8, std.mem.span(branch_name));
        }
        snapshot.ahead_behind = readAheadBehind(&runtime, repo, head);
    }

    snapshot.counts = readStatusCounts(&runtime, repo) catch .{};
    return snapshot;
}

fn readAheadBehind(runtime: *Runtime, repo: *GitRepository, head: *GitReference) ?git_state.AheadBehind {
    const local_oid = runtime.git_reference_target(head) orelse return null;
    var upstream: *GitReference = undefined;
    if (runtime.git_branch_upstream(&upstream, head) != 0) return null;
    defer runtime.git_reference_free(upstream);
    const upstream_oid = runtime.git_reference_target(upstream) orelse return null;

    var ahead: usize = 0;
    var behind: usize = 0;
    if (runtime.git_graph_ahead_behind(&ahead, &behind, repo, local_oid, upstream_oid) != 0) return null;
    return .{
        .behind = @intCast(@min(behind, std.math.maxInt(u32))),
        .ahead = @intCast(@min(ahead, std.math.maxInt(u32))),
    };
}

fn readStatusCounts(runtime: *Runtime, repo: *GitRepository) !git_state.WorktreeCounts {
    var opts = GitStatusOptions{};
    if (runtime.git_status_options_init(&opts, git_status_options_version) < 0) return error.Libgit2StatusFailed;
    opts.show = git_status_show_index_and_workdir;
    opts.flags = git_status_opt_include_untracked | git_status_opt_recurse_untracked_dirs;

    var counts = git_state.WorktreeCounts{};
    if (runtime.git_status_foreach_ext(repo, &opts, statusCallback, &counts) < 0) return error.Libgit2StatusFailed;
    return counts;
}

fn statusCallback(_: [*c]const u8, flags: c_uint, payload: ?*anyopaque) callconv(.c) c_int {
    const counts: *git_state.WorktreeCounts = @ptrCast(@alignCast(payload orelse return -1));
    if ((flags & git_status_conflicted) != 0) {
        counts.conflicts += 1;
        return 0;
    }
    if ((flags & git_status_wt_new) != 0) {
        counts.untracked += 1;
        return 0;
    }
    if ((flags & (git_status_index_new | git_status_index_modified | git_status_index_deleted | git_status_index_renamed | git_status_index_typechange)) != 0) {
        counts.staged += 1;
    }
    if ((flags & (git_status_wt_modified | git_status_wt_deleted | git_status_wt_typechange | git_status_wt_renamed | git_status_wt_unreadable)) != 0) {
        counts.unstaged += 1;
    }
    return 0;
}

fn lookup(lib: *std.DynLib, comptime T: type, name: [:0]const u8) !T {
    return lib.lookup(T, name) orelse error.MissingLibgit2Symbol;
}

fn openLibrary() !std.DynLib {
    const names: []const []const u8 = switch (builtin.os.tag) {
        .macos => &[_][]const u8{
            "/opt/homebrew/lib/libgit2.dylib",
            "/usr/local/lib/libgit2.dylib",
            "libgit2.dylib",
            "libgit2.1.9.dylib",
        },
        .linux => &[_][]const u8{
            "libgit2.so.1.9",
            "libgit2.so.1.8",
            "libgit2.so.1.7",
            "libgit2.so",
        },
        else => &[_][]const u8{"libgit2"},
    };
    for (names) |name| {
        return std.DynLib.open(name) catch continue;
    }
    return error.Libgit2Unavailable;
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

test "reads branch counts and upstream through libgit2" {
    if (!available()) return error.SkipZigTest;

    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-libgit2-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const remote_path = try std.fmt.allocPrint(allocator, "{s}-remote.git", .{dir_path});
    defer allocator.free(remote_path);
    defer std.fs.cwd().deleteTree(remote_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-q", "-b", "main" });
    try writeFile(allocator, dir_path, "tracked.txt", "base\n");
    try runGit(allocator, dir_path, &.{ "git", "add", "tracked.txt" });
    try runGit(allocator, dir_path, &.{ "git", "-c", "user.name=shisa", "-c", "user.email=shisa@example.invalid", "commit", "-q", "-m", "base" });
    try runGit(allocator, "/tmp", &.{ "git", "init", "-q", "--bare", remote_path });
    try runGit(allocator, dir_path, &.{ "git", "remote", "add", "origin", remote_path });
    try runGit(allocator, dir_path, &.{ "git", "push", "-q", "-u", "origin", "main" });

    try writeFile(allocator, dir_path, "ahead.txt", "ahead\n");
    try runGit(allocator, dir_path, &.{ "git", "add", "ahead.txt" });
    try runGit(allocator, dir_path, &.{ "git", "-c", "user.name=shisa", "-c", "user.email=shisa@example.invalid", "commit", "-q", "-m", "ahead" });
    try writeFile(allocator, dir_path, "staged.txt", "staged\n");
    try runGit(allocator, dir_path, &.{ "git", "add", "staged.txt" });
    try writeFile(allocator, dir_path, "tracked.txt", "base\nunstaged\n");
    try writeFile(allocator, dir_path, "untracked.txt", "untracked\n");

    var snapshot = (try readSnapshot(allocator, dir_path)).?;
    defer snapshot.deinit(allocator);
    try std.testing.expectEqualStrings("main", snapshot.branch.?);
    try std.testing.expectEqual(@as(u32, 1), snapshot.counts.staged);
    try std.testing.expectEqual(@as(u32, 1), snapshot.counts.unstaged);
    try std.testing.expectEqual(@as(u32, 1), snapshot.counts.untracked);
    try std.testing.expectEqual(@as(u32, 0), snapshot.counts.conflicts);
    try std.testing.expect(snapshot.ahead_behind != null);
    try std.testing.expectEqual(@as(u32, 0), snapshot.ahead_behind.?.behind);
    try std.testing.expectEqual(@as(u32, 1), snapshot.ahead_behind.?.ahead);
    try std.testing.expect(!snapshot.detached);
}

fn writeFile(allocator: std.mem.Allocator, root: []const u8, name: []const u8, contents: []const u8) !void {
    const path = try std.fs.path.join(allocator, &.{ root, name });
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(contents);
}
