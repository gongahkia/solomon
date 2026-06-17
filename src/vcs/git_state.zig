const std = @import("std");

pub const RebaseState = enum {
    none,
    apply,
    merge,
    interactive,
};

pub const SequencerState = enum {
    none,
    single,
    sequence,
};

pub const BisectState = struct {
    active: bool = false,
    current: bool = false,
    good: bool = false,
    bad: bool = false,
};

pub fn detectBisectState(git_dir: std.fs.Dir) BisectState {
    return .{
        .active = entryExists(git_dir, "BISECT_LOG") or entryExists(git_dir, "refs/bisect"),
        .current = entryExists(git_dir, "BISECT_HEAD"),
        .good = entryExists(git_dir, "refs/bisect/good"),
        .bad = entryExists(git_dir, "refs/bisect/bad"),
    };
}

pub fn detectAmState(git_dir: std.fs.Dir) bool {
    return entryExists(git_dir, "rebase-apply/applying") or
        entryExists(git_dir, "rebase-apply/patch") or
        entryExists(git_dir, "rebase-apply/msg");
}

pub fn detectCherryPickState(git_dir: std.fs.Dir) SequencerState {
    if (entryExists(git_dir, "sequencer/todo")) return .sequence;
    if (entryExists(git_dir, "CHERRY_PICK_HEAD")) return .single;
    return .none;
}

pub fn detectRevertState(git_dir: std.fs.Dir) SequencerState {
    if (entryExists(git_dir, "sequencer/todo")) return .sequence;
    if (entryExists(git_dir, "REVERT_HEAD")) return .single;
    return .none;
}

pub fn detectMergeState(git_dir: std.fs.Dir) bool {
    return entryExists(git_dir, "MERGE_HEAD");
}

pub fn detectDetachedHead(allocator: std.mem.Allocator, git_dir: std.fs.Dir) !bool {
    const head = git_dir.readFileAlloc(allocator, "HEAD", 4096) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(head);
    return !std.mem.startsWith(u8, std.mem.trim(u8, head, " \t\r\n"), "ref: refs/");
}

pub fn detectRebaseState(git_dir: std.fs.Dir) !RebaseState {
    if (entryExists(git_dir, "rebase-merge")) {
        if (entryExists(git_dir, "rebase-merge/interactive") or entryExists(git_dir, "rebase-merge/git-rebase-todo")) {
            return .interactive;
        }
        return .merge;
    }
    if (entryExists(git_dir, "rebase-apply")) return .apply;
    return .none;
}

fn entryExists(dir: std.fs.Dir, sub_path: []const u8) bool {
    dir.access(sub_path, .{}) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return false,
    };
    return true;
}

test "detects absent rebase state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(RebaseState.none, try detectRebaseState(git_dir));
}

test "detects apply rebase state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath(".git/rebase-apply");
    var git_dir = try openGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(RebaseState.apply, try detectRebaseState(git_dir));
}

test "detects merge rebase state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath(".git/rebase-merge");
    var git_dir = try openGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(RebaseState.merge, try detectRebaseState(git_dir));
}

test "detects interactive rebase state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath(".git/rebase-merge");
    try tmp.dir.writeFile(.{ .sub_path = ".git/rebase-merge/git-rebase-todo", .data = "pick abc123 msg\n" });
    var git_dir = try openGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(RebaseState.interactive, try detectRebaseState(git_dir));
}

test "detects absent merge state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expect(!detectMergeState(git_dir));
}

test "detects merge state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "MERGE_HEAD", .data = "abc123\n" });
    try std.testing.expect(detectMergeState(git_dir));
}

test "detects absent cherry-pick state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(SequencerState.none, detectCherryPickState(git_dir));
}

test "detects single cherry-pick state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "CHERRY_PICK_HEAD", .data = "abc123\n" });
    try std.testing.expectEqual(SequencerState.single, detectCherryPickState(git_dir));
}

test "detects sequenced cherry-pick state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.makePath("sequencer");
    try git_dir.writeFile(.{ .sub_path = "sequencer/todo", .data = "pick abc123 msg\n" });
    try std.testing.expectEqual(SequencerState.sequence, detectCherryPickState(git_dir));
}

test "detects absent revert state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expectEqual(SequencerState.none, detectRevertState(git_dir));
}

test "detects single revert state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "REVERT_HEAD", .data = "abc123\n" });
    try std.testing.expectEqual(SequencerState.single, detectRevertState(git_dir));
}

test "detects sequenced revert state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.makePath("sequencer");
    try git_dir.writeFile(.{ .sub_path = "sequencer/todo", .data = "revert abc123 msg\n" });
    try std.testing.expectEqual(SequencerState.sequence, detectRevertState(git_dir));
}

test "detects absent bisect state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    const state = detectBisectState(git_dir);
    try std.testing.expect(!state.active);
    try std.testing.expect(!state.current);
}

test "detects bisect good bad and current state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.makePath("refs/bisect");
    try git_dir.writeFile(.{ .sub_path = "refs/bisect/good", .data = "abc123\n" });
    try git_dir.writeFile(.{ .sub_path = "refs/bisect/bad", .data = "def456\n" });
    try git_dir.writeFile(.{ .sub_path = "BISECT_HEAD", .data = "fedcba\n" });
    const state = detectBisectState(git_dir);
    try std.testing.expect(state.active);
    try std.testing.expect(state.current);
    try std.testing.expect(state.good);
    try std.testing.expect(state.bad);
}

test "detects absent git am state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath(".git/rebase-apply");
    var git_dir = try openGitDir(&tmp);
    defer git_dir.close();
    try std.testing.expect(!detectAmState(git_dir));
}

test "detects git am state" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath(".git/rebase-apply");
    var git_dir = try openGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "rebase-apply/applying", .data = "" });
    try std.testing.expect(detectAmState(git_dir));
}

test "detects attached HEAD" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "HEAD", .data = "ref: refs/heads/main\n" });
    try std.testing.expect(!try detectDetachedHead(std.testing.allocator, git_dir));
}

test "detects detached HEAD" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var git_dir = try makeGitDir(&tmp);
    defer git_dir.close();
    try git_dir.writeFile(.{ .sub_path = "HEAD", .data = "0123456789abcdef0123456789abcdef01234567\n" });
    try std.testing.expect(try detectDetachedHead(std.testing.allocator, git_dir));
}

fn makeGitDir(tmp: *std.testing.TmpDir) !std.fs.Dir {
    try tmp.dir.makeDir(".git");
    return openGitDir(tmp);
}

fn openGitDir(tmp: *std.testing.TmpDir) !std.fs.Dir {
    return tmp.dir.openDir(".git", .{});
}
