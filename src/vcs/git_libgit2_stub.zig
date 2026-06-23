const std = @import("std");
const git_state = @import("git_state.zig");

pub const Snapshot = struct {
    branch: ?[]u8 = null,
    counts: git_state.WorktreeCounts = .{},
    ahead_behind: ?git_state.AheadBehind = null,
    detached: bool = false,

    pub fn deinit(self: *Snapshot, _: std.mem.Allocator) void {
        self.* = .{};
    }
};

pub fn available() bool {
    return false;
}

pub fn readSnapshot(_: std.mem.Allocator, _: []const u8) !?Snapshot {
    return null;
}
