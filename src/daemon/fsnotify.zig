const std = @import("std");
const builtin = @import("builtin");

pub const Backend = enum {
    fsevents,
    inotify,
    unsupported,
};

pub const default_debounce_ms: u64 = 50;

pub const WatchPath = struct {
    path: []const u8,
    recursive: bool = false,
};

pub const Scope = struct {
    module_id: []const u8,
    cwd: []const u8,
    paths: []const WatchPath,
    debounce_ms: u64 = default_debounce_ms,
};

pub const Invalidation = struct {
    module_id: []const u8,
    cwd: []const u8,
};

pub const InotifyLimitStatus = struct {
    watched_paths: usize,
    max_user_watches: ?u64,
    within_limit: ?bool,
    remaining: ?u64,
};

const OwnedPath = struct {
    path: []u8,
    recursive: bool,
};

const Registration = struct {
    module_id: []u8,
    cwd: []u8,
    paths: []OwnedPath,
    debounce_ns: u64,
    pending: bool = false,
    last_event_ns: u64 = 0,

    fn deinit(self: *Registration, allocator: std.mem.Allocator) void {
        allocator.free(self.module_id);
        allocator.free(self.cwd);
        for (self.paths) |owned| allocator.free(owned.path);
        allocator.free(self.paths);
        self.* = undefined;
    }
};

pub const Watcher = struct {
    allocator: std.mem.Allocator,
    backend: Backend,
    registrations: std.ArrayList(Registration),

    pub fn init(allocator: std.mem.Allocator) Watcher {
        return .{
            .allocator = allocator,
            .backend = selectBackend(builtin.os.tag),
            .registrations = .empty,
        };
    }

    pub fn deinit(self: *Watcher) void {
        for (self.registrations.items) |*registration| registration.deinit(self.allocator);
        self.registrations.deinit(self.allocator);
        self.* = undefined;
    }

    pub fn watch(self: *Watcher, scope: Scope) !void {
        if (self.hasScope(scope.module_id, scope.cwd)) return;

        const module_id = try self.allocator.dupe(u8, scope.module_id);
        errdefer self.allocator.free(module_id);
        const cwd = try self.allocator.dupe(u8, scope.cwd);
        errdefer self.allocator.free(cwd);
        const paths = try self.allocator.alloc(OwnedPath, scope.paths.len);
        errdefer self.allocator.free(paths);

        var initialized: usize = 0;
        errdefer {
            for (paths[0..initialized]) |owned| self.allocator.free(owned.path);
        }

        for (scope.paths, 0..) |path, index| {
            paths[index] = .{
                .path = try self.allocator.dupe(u8, path.path),
                .recursive = path.recursive,
            };
            initialized += 1;
        }

        try self.registrations.append(self.allocator, .{
            .module_id = module_id,
            .cwd = cwd,
            .paths = paths,
            .debounce_ns = scope.debounce_ms * std.time.ns_per_ms,
        });
    }

    pub fn recordEvent(self: *Watcher, path: []const u8, timestamp_ns: u64) void {
        for (self.registrations.items) |*registration| {
            if (registrationMatches(registration.*, path)) {
                registration.pending = true;
                registration.last_event_ns = timestamp_ns;
            }
        }
    }

    pub fn nextInvalidation(self: *Watcher, timestamp_ns: u64) ?Invalidation {
        for (self.registrations.items) |*registration| {
            if (!registration.pending) continue;
            if (timestamp_ns < registration.last_event_ns) continue;
            if (timestamp_ns - registration.last_event_ns < registration.debounce_ns) continue;
            registration.pending = false;
            return .{
                .module_id = registration.module_id,
                .cwd = registration.cwd,
            };
        }
        return null;
    }

    pub fn count(self: Watcher) usize {
        return self.registrations.items.len;
    }

    pub fn watchedPathCount(self: Watcher) usize {
        var total: usize = 0;
        for (self.registrations.items) |registration| total += registration.paths.len;
        return total;
    }

    pub fn inotifyLimitStatus(self: Watcher, max_user_watches: ?u64) InotifyLimitStatus {
        return inotifyLimitStatusForCount(self.watchedPathCount(), max_user_watches);
    }

    pub fn hasScope(self: Watcher, module_id: []const u8, cwd: []const u8) bool {
        for (self.registrations.items) |registration| {
            if (std.mem.eql(u8, registration.module_id, module_id) and std.mem.eql(u8, registration.cwd, cwd)) return true;
        }
        return false;
    }
};

pub fn selectBackend(os_tag: std.Target.Os.Tag) Backend {
    return switch (os_tag) {
        .macos => .fsevents,
        .linux => .inotify,
        else => .unsupported,
    };
}

pub fn readLinuxMaxUserWatches(allocator: std.mem.Allocator) !?u64 {
    if (builtin.os.tag != .linux) return null;
    const contents = std.fs.cwd().readFileAlloc(allocator, "/proc/sys/fs/inotify/max_user_watches", 128) catch |err| switch (err) {
        error.FileNotFound, error.AccessDenied => return null,
        else => return err,
    };
    defer allocator.free(contents);
    return parseUnsigned(contents);
}

pub fn inotifyLimitStatusForCount(watched_paths: usize, max_user_watches: ?u64) InotifyLimitStatus {
    const watched: u64 = @intCast(watched_paths);
    const limit = max_user_watches orelse return .{
        .watched_paths = watched_paths,
        .max_user_watches = null,
        .within_limit = null,
        .remaining = null,
    };
    return .{
        .watched_paths = watched_paths,
        .max_user_watches = limit,
        .within_limit = watched <= limit,
        .remaining = if (watched <= limit) limit - watched else 0,
    };
}

fn parseUnsigned(contents: []const u8) !u64 {
    const trimmed = std.mem.trim(u8, contents, " \t\r\n");
    if (trimmed.len == 0) return error.InvalidUnsigned;
    return std.fmt.parseInt(u64, trimmed, 10);
}

fn registrationMatches(registration: Registration, path: []const u8) bool {
    for (registration.paths) |watch_path| {
        if (pathMatches(watch_path, path)) return true;
    }
    return false;
}

fn pathMatches(watch_path: OwnedPath, path: []const u8) bool {
    if (std.mem.eql(u8, watch_path.path, path)) return true;
    if (!watch_path.recursive) return false;
    if (!std.mem.startsWith(u8, path, watch_path.path)) return false;
    if (path.len == watch_path.path.len) return true;
    return isPathSeparator(path[watch_path.path.len]);
}

fn isPathSeparator(byte: u8) bool {
    return byte == '/' or byte == '\\';
}

test "selects platform backends" {
    try std.testing.expectEqual(Backend.fsevents, selectBackend(.macos));
    try std.testing.expectEqual(Backend.inotify, selectBackend(.linux));
    try std.testing.expectEqual(Backend.unsupported, selectBackend(.freebsd));
}

test "owns watched scope paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expectEqual(@as(usize, 1), watcher.count());
    try std.testing.expectEqualStrings("git_branch", watcher.registrations.items[0].module_id);
    try std.testing.expectEqualStrings("/repo/.git/index", watcher.registrations.items[0].paths[1].path);
}

test "deduplicates watched scopes" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo/.git/HEAD" }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expect(watcher.hasScope("git_branch", "/repo"));
    try std.testing.expectEqual(@as(usize, 1), watcher.count());
}

test "counts watched paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expectEqual(@as(usize, 2), watcher.watchedPathCount());
}

test "reports inotify limit status" {
    const ok = inotifyLimitStatusForCount(8, 16);
    try std.testing.expectEqual(@as(usize, 8), ok.watched_paths);
    try std.testing.expectEqual(@as(u64, 16), ok.max_user_watches.?);
    try std.testing.expect(ok.within_limit.?);
    try std.testing.expectEqual(@as(u64, 8), ok.remaining.?);

    const exceeded = inotifyLimitStatusForCount(17, 16);
    try std.testing.expect(!exceeded.within_limit.?);
    try std.testing.expectEqual(@as(u64, 0), exceeded.remaining.?);

    const unknown = inotifyLimitStatusForCount(4, null);
    try std.testing.expect(unknown.within_limit == null);
}

test "parses trimmed unsigned sysctl values" {
    try std.testing.expectEqual(@as(u64, 524288), try parseUnsigned("524288\n"));
    try std.testing.expectError(error.InvalidCharacter, parseUnsigned("nope\n"));
}

test "debounces invalidations by scope" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 50,
    });

    watcher.recordEvent("/repo/.git/index", 1 * std.time.ns_per_ms);
    try std.testing.expect(watcher.nextInvalidation(40 * std.time.ns_per_ms) == null);
    watcher.recordEvent("/repo/.git/HEAD", 45 * std.time.ns_per_ms);
    try std.testing.expect(watcher.nextInvalidation(90 * std.time.ns_per_ms) == null);

    const invalidation = watcher.nextInvalidation(96 * std.time.ns_per_ms).?;
    try std.testing.expectEqualStrings("git_branch", invalidation.module_id);
    try std.testing.expectEqualStrings("/repo", invalidation.cwd);
    try std.testing.expect(watcher.nextInvalidation(150 * std.time.ns_per_ms) == null);
}

test "recursive watches match only descendants" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo", .recursive = true }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 0,
    });

    watcher.recordEvent("/repo-other/file", 1);
    try std.testing.expect(watcher.nextInvalidation(1) == null);
    watcher.recordEvent("/repo/src/main.zig", 2);
    try std.testing.expect(watcher.nextInvalidation(2) != null);
}

test "exact watches ignore child paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo/.git/HEAD" }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 0,
    });

    watcher.recordEvent("/repo/.git/HEAD.lock", 1);
    try std.testing.expect(watcher.nextInvalidation(1) == null);
    watcher.recordEvent("/repo/.git/HEAD", 2);
    try std.testing.expect(watcher.nextInvalidation(2) != null);
}
