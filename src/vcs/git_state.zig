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

pub const PromptSignal = struct {
    glyph: []const u8,
    a11y: []const u8,
};

pub const WorktreeCounts = struct {
    staged: u32 = 0,
    unstaged: u32 = 0,
    untracked: u32 = 0,
    conflicts: u32 = 0,
};

pub const SparseCheckoutState = enum {
    none,
    non_cone,
    cone,
};

pub const AheadBehind = struct {
    behind: u32 = 0,
    ahead: u32 = 0,
};

pub const SubmoduleSummary = struct {
    dirty: u32 = 0,
    uninitialized: u32 = 0,
    conflicts: u32 = 0,
    ahead: u32 = 0,
    behind: u32 = 0,
};

pub fn parseAheadBehind(output: []const u8) ?AheadBehind {
    var tokens = std.mem.tokenizeAny(u8, output, " \t\r\n");
    const behind_text = tokens.next() orelse return null;
    const ahead_text = tokens.next() orelse return null;
    return .{
        .behind = std.fmt.parseInt(u32, behind_text, 10) catch return null,
        .ahead = std.fmt.parseInt(u32, ahead_text, 10) catch return null,
    };
}

pub fn parseSubmoduleStatus(output: []const u8) SubmoduleSummary {
    var summary = SubmoduleSummary{};
    var lines = std.mem.splitScalar(u8, output, '\n');
    while (lines.next()) |line| {
        if (line.len == 0) continue;
        switch (line[0]) {
            '-' => summary.uninitialized += 1,
            '+' => summary.dirty += 1,
            'U' => summary.conflicts += 1,
            else => {},
        }
        if (parseSubmoduleAheadBehind(line)) |counts| {
            summary.ahead += counts.ahead;
            summary.behind += counts.behind;
        }
    }
    return summary;
}

fn parseSubmoduleAheadBehind(line: []const u8) ?AheadBehind {
    const marker = std.mem.indexOf(u8, line, "ahead ") orelse return parseSubmoduleBehindOnly(line);
    const ahead_start = marker + "ahead ".len;
    const ahead_end = scanDigits(line, ahead_start);
    if (ahead_end == ahead_start) return null;
    const ahead = std.fmt.parseInt(u32, line[ahead_start..ahead_end], 10) catch return null;
    var behind: u32 = 0;
    if (std.mem.indexOfPos(u8, line, ahead_end, "behind ")) |behind_marker| {
        const behind_start = behind_marker + "behind ".len;
        const behind_end = scanDigits(line, behind_start);
        if (behind_end > behind_start) behind = std.fmt.parseInt(u32, line[behind_start..behind_end], 10) catch return null;
    }
    return .{ .ahead = ahead, .behind = behind };
}

fn parseSubmoduleBehindOnly(line: []const u8) ?AheadBehind {
    const marker = std.mem.indexOf(u8, line, "behind ") orelse return null;
    const start = marker + "behind ".len;
    const end = scanDigits(line, start);
    if (end == start) return null;
    return .{ .behind = std.fmt.parseInt(u32, line[start..end], 10) catch return null };
}

fn scanDigits(line: []const u8, start: usize) usize {
    var index = start;
    while (index < line.len and std.ascii.isDigit(line[index])) : (index += 1) {}
    return index;
}

pub fn parsePorcelainCounts(output: []const u8) WorktreeCounts {
    var counts = WorktreeCounts{};
    var lines = std.mem.splitScalar(u8, output, '\n');
    while (lines.next()) |line| {
        if (line.len < 2) continue;
        const x = line[0];
        const y = line[1];
        if (x == '?' and y == '?') {
            counts.untracked += 1;
            continue;
        }
        if (isConflictStatus(x, y)) {
            counts.conflicts += 1;
            continue;
        }
        if (x != ' ' and x != '?') counts.staged += 1;
        if (y != ' ' and y != '?') counts.unstaged += 1;
    }
    return counts;
}

pub fn parseSparseCheckoutState(config: []const u8) SparseCheckoutState {
    var sparse = false;
    var cone = false;
    var lines = std.mem.splitScalar(u8, config, '\n');
    while (lines.next()) |line| {
        const kv = keyValue(line) orelse continue;
        if (std.ascii.eqlIgnoreCase(kv.key, "core.sparsecheckout") and boolValue(kv.value)) sparse = true;
        if (std.ascii.eqlIgnoreCase(kv.key, "index.sparse") and boolValue(kv.value)) sparse = true;
        if (std.ascii.eqlIgnoreCase(kv.key, "core.sparsecheckoutcone") and boolValue(kv.value)) cone = true;
    }
    if (!sparse) return .none;
    return if (cone) .cone else .non_cone;
}

pub fn parseStashCount(output: []const u8) u32 {
    var count: u32 = 0;
    var lines = std.mem.splitScalar(u8, output, '\n');
    while (lines.next()) |line| {
        if (std.mem.startsWith(u8, line, "stash@{")) count += 1;
    }
    return count;
}

fn keyValue(line: []const u8) ?struct { key: []const u8, value: []const u8 } {
    const split = std.mem.indexOfScalar(u8, line, '=') orelse return null;
    return .{
        .key = std.mem.trim(u8, line[0..split], " \t\r\n"),
        .value = std.mem.trim(u8, line[split + 1 ..], " \t\r\n"),
    };
}

fn boolValue(value: []const u8) bool {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    return std.ascii.eqlIgnoreCase(trimmed, "true") or std.mem.eql(u8, trimmed, "1") or std.ascii.eqlIgnoreCase(trimmed, "yes");
}

fn isConflictStatus(x: u8, y: u8) bool {
    return (x == 'D' and y == 'D') or
        (x == 'A' and y == 'U') or
        (x == 'U' and y == 'D') or
        (x == 'U' and y == 'A') or
        (x == 'D' and y == 'U') or
        (x == 'A' and y == 'A') or
        (x == 'U' and y == 'U');
}

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

pub fn rebaseSignal(state: RebaseState) ?PromptSignal {
    return switch (state) {
        .none => null,
        .apply => .{ .glyph = "rebase:apply", .a11y = "rebase in progress using apply backend" },
        .merge => .{ .glyph = "rebase:merge", .a11y = "rebase in progress using merge backend" },
        .interactive => .{ .glyph = "rebase:i", .a11y = "interactive rebase in progress" },
    };
}

pub fn mergeSignal(active: bool) ?PromptSignal {
    return if (active) .{ .glyph = "merge", .a11y = "merge in progress" } else null;
}

pub fn cherryPickSignal(state: SequencerState) ?PromptSignal {
    return switch (state) {
        .none => null,
        .single => .{ .glyph = "pick", .a11y = "cherry-pick in progress" },
        .sequence => .{ .glyph = "pick:seq", .a11y = "cherry-pick sequence in progress" },
    };
}

pub fn revertSignal(state: SequencerState) ?PromptSignal {
    return switch (state) {
        .none => null,
        .single => .{ .glyph = "revert", .a11y = "revert in progress" },
        .sequence => .{ .glyph = "revert:seq", .a11y = "revert sequence in progress" },
    };
}

pub fn bisectSignal(state: BisectState) ?PromptSignal {
    if (!state.active and !state.current) return null;
    if (state.current) return .{ .glyph = "bisect:current", .a11y = "bisect current commit under test" };
    if (state.good and state.bad) return .{ .glyph = "bisect:good/bad", .a11y = "bisect has good and bad bounds" };
    if (state.good) return .{ .glyph = "bisect:good", .a11y = "bisect has known good commit" };
    if (state.bad) return .{ .glyph = "bisect:bad", .a11y = "bisect has known bad commit" };
    return .{ .glyph = "bisect", .a11y = "bisect in progress" };
}

pub fn amSignal(active: bool) ?PromptSignal {
    return if (active) .{ .glyph = "am", .a11y = "git am patch apply in progress" } else null;
}

pub fn detachedHeadSignal(active: bool) ?PromptSignal {
    return if (active) .{ .glyph = "detached", .a11y = "detached HEAD" } else null;
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

test "formats git state signals with glyph and a11y labels" {
    try expectSignal(rebaseSignal(.interactive).?, "rebase:i", "interactive rebase in progress");
    try expectSignal(mergeSignal(true).?, "merge", "merge in progress");
    try expectSignal(cherryPickSignal(.sequence).?, "pick:seq", "cherry-pick sequence in progress");
    try expectSignal(revertSignal(.sequence).?, "revert:seq", "revert sequence in progress");
    try expectSignal(bisectSignal(.{ .active = true, .current = true }).?, "bisect:current", "bisect current commit under test");
    try expectSignal(amSignal(true).?, "am", "git am patch apply in progress");
    try expectSignal(detachedHeadSignal(true).?, "detached", "detached HEAD");
}

test "parses porcelain working tree counts" {
    const counts = parsePorcelainCounts(
        \\M  staged.txt
        \\ M unstaged.txt
        \\MM both.txt
        \\?? new.txt
        \\UU conflict.txt
        \\
    );
    try std.testing.expectEqual(@as(u32, 2), counts.staged);
    try std.testing.expectEqual(@as(u32, 2), counts.unstaged);
    try std.testing.expectEqual(@as(u32, 1), counts.untracked);
    try std.testing.expectEqual(@as(u32, 1), counts.conflicts);
}

test "parses stash count" {
    const count = parseStashCount(
        \\stash@{0}: WIP on main: abc one
        \\stash@{1}: On feature: msg
        \\
    );
    try std.testing.expectEqual(@as(u32, 2), count);
}

test "parses sparse checkout state" {
    try std.testing.expectEqual(SparseCheckoutState.none, parseSparseCheckoutState("core.sparseCheckout=false\n"));
    try std.testing.expectEqual(SparseCheckoutState.non_cone, parseSparseCheckoutState("core.sparseCheckout=true\n"));
    try std.testing.expectEqual(SparseCheckoutState.cone, parseSparseCheckoutState("core.sparseCheckout=true\ncore.sparseCheckoutCone=true\n"));
    try std.testing.expectEqual(SparseCheckoutState.cone, parseSparseCheckoutState("index.sparse=true\ncore.sparseCheckoutCone=true\n"));
}

test "parses ahead behind counts" {
    const counts = parseAheadBehind("3\t5\n").?;
    try std.testing.expectEqual(@as(u32, 3), counts.behind);
    try std.testing.expectEqual(@as(u32, 5), counts.ahead);
    try std.testing.expect(parseAheadBehind("bad\n") == null);
}

test "parses submodule summary" {
    const summary = parseSubmoduleStatus(
        \\ 1234567 clean (heads/main)
        \\+abcdef0 dirty (heads/main ahead 2, behind 1)
        \\-1111111 missing libs/a
        \\U2222222 conflict libs/b
        \\ 3333333 old (heads/main behind 3)
        \\
    );
    try std.testing.expectEqual(@as(u32, 1), summary.dirty);
    try std.testing.expectEqual(@as(u32, 1), summary.uninitialized);
    try std.testing.expectEqual(@as(u32, 1), summary.conflicts);
    try std.testing.expectEqual(@as(u32, 2), summary.ahead);
    try std.testing.expectEqual(@as(u32, 4), summary.behind);
}

fn expectSignal(signal: PromptSignal, glyph: []const u8, a11y: []const u8) !void {
    try std.testing.expectEqualStrings(glyph, signal.glyph);
    try std.testing.expectEqualStrings(a11y, signal.a11y);
}

fn makeGitDir(tmp: *std.testing.TmpDir) !std.fs.Dir {
    try tmp.dir.makeDir(".git");
    return openGitDir(tmp);
}

fn openGitDir(tmp: *std.testing.TmpDir) !std.fs.Dir {
    return tmp.dir.openDir(".git", .{});
}
