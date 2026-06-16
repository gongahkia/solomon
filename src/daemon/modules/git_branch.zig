const std = @import("std");

pub const module_id = "git_branch";
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

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    valid: bool = false,
    in_flight: bool = false,
    generation: u64 = 0,
    cwd: ?[]u8 = null,
    segment: ?[]u8 = null,
    worker: ?std.Thread = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        const worker = self.takeWorker();
        if (worker) |thread| thread.join();
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clear(allocator);
    }

    pub fn invalidate(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();

        if (self.cwd == null or !std.mem.eql(u8, self.cwd.?, cwd_path)) return;
        self.generation += 1;
        if (self.in_flight) {
            if (self.segment) |value| allocator.free(value);
            self.segment = null;
            self.valid = false;
            return;
        }
        self.clear(allocator);
    }

    pub fn render(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
        const worker = self.takeWorker();
        if (worker) |thread| thread.join();
        self.mutex.lock();
        defer self.mutex.unlock();

        if (self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path)) {
            if (self.segment) |segment| return try allocator.dupe(u8, segment);
            return null;
        }

        self.clear(allocator);
        self.valid = true;
        self.cwd = try allocator.dupe(u8, cwd_path);
        self.segment = try probe(allocator, cwd_path);

        if (self.segment) |segment| return try allocator.dupe(u8, segment);
        return null;
    }

    pub const AsyncRender = struct {
        segment: ?[]u8 = null,
        pending: bool = false,

        pub fn deinit(self: *AsyncRender, allocator: std.mem.Allocator) void {
            if (self.segment) |segment| allocator.free(segment);
            self.* = .{};
        }
    };

    pub fn renderAsync(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8) !AsyncRender {
        self.joinFinishedWorker();

        self.mutex.lock();
        if (self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path)) {
            const segment = if (self.segment) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return .{ .segment = segment };
        }
        if (self.in_flight) {
            self.mutex.unlock();
            return .{ .pending = true };
        }
        self.mutex.unlock();

        if (!(try looksLikeGitWorktree(allocator, cwd_path))) {
            self.mutex.lock();
            defer self.mutex.unlock();
            self.clear(allocator);
            self.valid = true;
            self.cwd = try allocator.dupe(u8, cwd_path);
            return .{};
        }

        const worker_cwd = try allocator.dupe(u8, cwd_path);
        errdefer allocator.free(worker_cwd);

        self.mutex.lock();
        self.clear(allocator);
        self.cwd = try allocator.dupe(u8, cwd_path);
        self.in_flight = true;
        self.generation += 1;
        const generation = self.generation;
        self.mutex.unlock();

        const worker = std.Thread.spawn(.{}, asyncProbe, .{ self, allocator, worker_cwd, generation }) catch |err| {
            self.mutex.lock();
            self.clear(allocator);
            self.mutex.unlock();
            return err;
        };
        self.mutex.lock();
        self.worker = worker;
        self.mutex.unlock();

        return .{ .pending = true };
    }

    fn takeWorker(self: *Cache) ?std.Thread {
        self.mutex.lock();
        defer self.mutex.unlock();
        const worker = self.worker;
        self.worker = null;
        return worker;
    }

    fn joinFinishedWorker(self: *Cache) void {
        self.mutex.lock();
        const should_join = !self.in_flight and self.worker != null;
        const worker = if (should_join) self.worker else null;
        if (should_join) self.worker = null;
        self.mutex.unlock();
        if (worker) |thread| thread.join();
    }

    fn clear(self: *Cache, allocator: std.mem.Allocator) void {
        if (self.cwd) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.valid = false;
        self.in_flight = false;
        self.cwd = null;
        self.segment = null;
    }
};

pub const WatchScope = struct {
    cwd: []u8,
    root_path: []u8,
    head_path: []u8,
    index_path: []u8,
    paths: [3]WatchPath,

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
        allocator.free(self.head_path);
        allocator.free(self.index_path);
        self.* = undefined;
    }
};

pub fn watchScope(allocator: std.mem.Allocator, cwd_path: []const u8) !?WatchScope {
    const root_path = (try findGitRoot(allocator, cwd_path)) orelse return null;
    errdefer allocator.free(root_path);
    const cwd = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(cwd);
    const head_path = try std.fs.path.join(allocator, &.{ root_path, ".git", "HEAD" });
    errdefer allocator.free(head_path);
    const index_path = try std.fs.path.join(allocator, &.{ root_path, ".git", "index" });
    errdefer allocator.free(index_path);

    return .{
        .cwd = cwd,
        .root_path = root_path,
        .head_path = head_path,
        .index_path = index_path,
        .paths = .{
            .{ .path = head_path },
            .{ .path = index_path },
            .{ .path = root_path, .recursive = true },
        },
    };
}

fn asyncProbe(cache: *Cache, allocator: std.mem.Allocator, cwd_path: []u8, generation: u64) void {
    defer allocator.free(cwd_path);
    const segment = probe(allocator, cwd_path) catch null;

    cache.mutex.lock();
    defer cache.mutex.unlock();
    if (cache.generation != generation or cache.cwd == null or !std.mem.eql(u8, cache.cwd.?, cwd_path)) {
        if (segment) |value| allocator.free(value);
        cache.in_flight = false;
        return;
    }
    if (cache.segment) |value| allocator.free(value);
    cache.segment = segment;
    cache.valid = true;
    cache.in_flight = false;
}

pub fn probe(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    const branch_result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "branch", "--show-current" },
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(branch_result.stdout);
    defer allocator.free(branch_result.stderr);

    if (!exitedZero(branch_result.term)) return null;

    const branch = std.mem.trim(u8, branch_result.stdout, " \t\r\n");
    if (branch.len == 0) return null;

    const dirty = try isDirty(allocator, cwd_path);
    return try std.fmt.allocPrint(allocator, "git:{s}{s}", .{ branch, if (dirty) "*" else "" });
}

fn looksLikeGitWorktree(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const root = try findGitRoot(allocator, cwd_path);
    if (root) |path| {
        allocator.free(path);
        return true;
    }
    return false;
}

fn findGitRoot(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const dot_git = try std.fs.path.join(allocator, &.{ current, ".git" });
        const found = found: {
            std.fs.cwd().access(dot_git, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(dot_git);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(dot_git);
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

fn isDirty(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const status_result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "status", "--porcelain" },
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return false;
    defer allocator.free(status_result.stdout);
    defer allocator.free(status_result.stderr);

    return exitedZero(status_result.term) and std.mem.trim(u8, status_result.stdout, " \t\r\n").len > 0;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
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
    try std.testing.expect(exitedZero(result.term));
}

test "hides outside git repo" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{};
    defer cache.deinit(allocator);
    try std.testing.expect(try cache.render(allocator, dir_path) == null);
}

test "renders branch and dirty indicator" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    var cache = Cache{};
    defer cache.deinit(allocator);
    const rendered = (try cache.render(allocator, dir_path)).?;
    defer allocator.free(rendered);
    try std.testing.expectEqualStrings("git:main*", rendered);
}

test "watch scope includes git metadata and worktree" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var watched = (try watchScope(allocator, dir_path)).?;
    defer watched.deinit(allocator);
    const head_path = try std.fmt.allocPrint(allocator, "{s}/.git/HEAD", .{dir_path});
    defer allocator.free(head_path);
    const index_path = try std.fmt.allocPrint(allocator, "{s}/.git/index", .{dir_path});
    defer allocator.free(index_path);

    try std.testing.expectEqualStrings(module_id, watched.scope().module_id);
    try std.testing.expectEqualStrings(dir_path, watched.scope().cwd);
    try std.testing.expectEqualStrings(head_path, watched.paths[0].path);
    try std.testing.expectEqualStrings(index_path, watched.paths[1].path);
    try std.testing.expectEqualStrings(dir_path, watched.paths[2].path);
    try std.testing.expect(watched.paths[2].recursive);
}

test "invalidate refreshes cached git segment" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var cache = Cache{};
    defer cache.deinit(allocator);
    const clean = (try cache.render(allocator, dir_path)).?;
    defer allocator.free(clean);
    try std.testing.expectEqualStrings("git:main", clean);

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    const cached = (try cache.render(allocator, dir_path)).?;
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("git:main", cached);

    cache.invalidate(allocator, dir_path);
    const refreshed = (try cache.render(allocator, dir_path)).?;
    defer allocator.free(refreshed);
    try std.testing.expectEqualStrings("git:main*", refreshed);
}

test "async render fills worker cache" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var cache = Cache{};
    defer cache.deinit(allocator);
    var first = try cache.renderAsync(allocator, dir_path);
    defer first.deinit(allocator);
    try std.testing.expect(first.pending);
    try std.testing.expect(first.segment == null);

    for (0..100) |_| {
        var rendered = try cache.renderAsync(allocator, dir_path);
        defer rendered.deinit(allocator);
        if (rendered.segment) |segment| {
            try std.testing.expectEqualStrings("git:main", segment);
            return;
        }
        std.Thread.sleep(10 * std.time.ns_per_ms);
    }
    return error.Timeout;
}

test "async render hides non git cwd without pending" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{};
    defer cache.deinit(allocator);
    var rendered = try cache.renderAsync(allocator, dir_path);
    defer rendered.deinit(allocator);
    try std.testing.expect(!rendered.pending);
    try std.testing.expect(rendered.segment == null);
}
