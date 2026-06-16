const std = @import("std");
const builtin = @import("builtin");

pub const Backend = enum {
    fsevents,
    inotify,
    unsupported,
};

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

pub const Invalidation = struct {
    module_id: []const u8,
    cwd: []const u8,
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
};

pub fn selectBackend(os_tag: std.Target.Os.Tag) Backend {
    return switch (os_tag) {
        .macos => .fsevents,
        .linux => .inotify,
        else => .unsupported,
    };
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
