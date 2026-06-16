const std = @import("std");

pub fn topDirsFromZshHistory(allocator: std.mem.Allocator, history: []const u8, max_dirs: usize) ![][]u8 {
    var counts = std.StringHashMap(u32).init(allocator);
    defer {
        var it = counts.iterator();
        while (it.next()) |entry| allocator.free(entry.key_ptr.*);
        counts.deinit();
    }

    var lines = std.mem.tokenizeScalar(u8, history, '\n');
    while (lines.next()) |line| {
        if (extractCdTarget(line)) |path| {
            const existing = counts.getEntry(path);
            if (existing) |entry| {
                entry.value_ptr.* += 1;
            } else {
                try counts.put(try allocator.dupe(u8, path), 1);
            }
        }
    }

    var out: std.ArrayList([]u8) = .empty;
    errdefer {
        for (out.items) |path| allocator.free(path);
        out.deinit(allocator);
    }

    while (out.items.len < max_dirs and counts.count() > 0) {
        var best_key: ?[]const u8 = null;
        var best_count: u32 = 0;
        var it = counts.iterator();
        while (it.next()) |entry| {
            if (entry.value_ptr.* > best_count) {
                best_count = entry.value_ptr.*;
                best_key = entry.key_ptr.*;
            }
        }
        const key = best_key orelse break;
        try out.append(allocator, try allocator.dupe(u8, key));
        const removed = counts.fetchRemove(key).?;
        allocator.free(removed.key);
    }

    return out.toOwnedSlice(allocator);
}

pub fn historyPath(allocator: std.mem.Allocator) ![]u8 {
    if (std.process.getEnvVarOwned(allocator, "HISTFILE")) |path| return path else |_| {}
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.zsh_history", .{home});
}

fn extractCdTarget(line: []const u8) ?[]const u8 {
    const command = if (std.mem.indexOfScalar(u8, line, ';')) |index| line[index + 1 ..] else line;
    const trimmed = std.mem.trim(u8, command, " \t\r\n");
    if (!std.mem.startsWith(u8, trimmed, "cd ")) return null;
    const path = std.mem.trim(u8, trimmed[3..], " \t\r\n'\"");
    if (path.len == 0 or path[0] != '/') return null;
    return path;
}

test "extracts top cd directories from zsh history" {
    const history =
        \\: 1:0;cd /repo/a
        \\: 2:0;ls
        \\: 3:0;cd /repo/b
        \\: 4:0;cd /repo/a
        \\
    ;
    const dirs = try topDirsFromZshHistory(std.testing.allocator, history, 2);
    defer {
        for (dirs) |dir| std.testing.allocator.free(dir);
        std.testing.allocator.free(dirs);
    }
    try std.testing.expectEqualStrings("/repo/a", dirs[0]);
    try std.testing.expectEqualStrings("/repo/b", dirs[1]);
}

test "ignores relative cd targets" {
    const dirs = try topDirsFromZshHistory(std.testing.allocator, "cd relative\ncd /abs\n", 10);
    defer {
        for (dirs) |dir| std.testing.allocator.free(dir);
        std.testing.allocator.free(dirs);
    }
    try std.testing.expectEqual(@as(usize, 1), dirs.len);
    try std.testing.expectEqualStrings("/abs", dirs[0]);
}
