const std = @import("std");
const builtin = @import("builtin");
const git_libgit2 = @import("vcs_git_libgit2");
const vcs_worktree = @import("vcs_worktree");

pub const module_id = "git_branch";

pub const Options = struct {
    show_dirty: bool = true,
    cache_ttl_ms: u32 = 250,
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

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    valid: bool = false,
    in_flight: bool = false,
    generation: u64 = 0,
    active_pid: ?std.process.Child.Id = null,
    cwd: ?[]u8 = null,
    segment: ?[]u8 = null,
    options: Options = .{},
    cached_at_ns: ?i128 = null,
    worker: ?std.Thread = null,

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.cancelActiveProcess();
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
            if (self.active_pid) |pid| killProcessId(pid);
            self.active_pid = null;
            if (self.segment) |value| allocator.free(value);
            self.segment = null;
            self.valid = false;
            self.in_flight = false;
            return;
        }
        self.clear(allocator);
    }

    pub fn render(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) !?[]u8 {
        const worker = self.takeWorker();
        if (worker) |thread| thread.join();
        self.mutex.lock();
        defer self.mutex.unlock();

        if (self.isReusable(cwd_path, options)) {
            if (self.segment) |segment| return try allocator.dupe(u8, segment);
            return null;
        }

        self.clear(allocator);
        self.valid = true;
        self.cwd = try allocator.dupe(u8, cwd_path);
        self.options = options;
        self.segment = try probe(allocator, cwd_path, options);
        self.cached_at_ns = std.time.nanoTimestamp();

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

    pub fn renderAsync(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) !AsyncRender {
        self.joinFinishedWorker();

        const cancelled_worker = self.cancelForRenderChange(allocator, cwd_path, options);
        if (cancelled_worker) |thread| thread.join();

        self.mutex.lock();
        if (self.isReusable(cwd_path, options)) {
            const segment = if (self.segment) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return .{ .segment = segment };
        }
        if (self.in_flight) {
            const stale_segment = if (self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path) and sameOptions(self.options, options))
                if (self.segment) |value| try allocator.dupe(u8, value) else null
            else
                null;
            self.mutex.unlock();
            return .{ .segment = stale_segment, .pending = true };
        }
        self.mutex.unlock();

        if (!(try looksLikeGitWorktree(allocator, cwd_path))) {
            self.mutex.lock();
            defer self.mutex.unlock();
            self.clear(allocator);
            self.valid = true;
            self.cwd = try allocator.dupe(u8, cwd_path);
            self.options = options;
            self.cached_at_ns = std.time.nanoTimestamp();
            return .{};
        }

        const worker_cwd = try allocator.dupe(u8, cwd_path);
        errdefer allocator.free(worker_cwd);

        self.mutex.lock();
        const refreshes_existing = self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path) and sameOptions(self.options, options);
        const stale_segment = if (refreshes_existing)
            if (self.segment) |value| try allocator.dupe(u8, value) else null
        else
            null;
        errdefer if (stale_segment) |value| allocator.free(value);
        if (!refreshes_existing) {
            self.clear(allocator);
            self.cwd = try allocator.dupe(u8, cwd_path);
            self.options = options;
        }
        self.in_flight = true;
        self.generation += 1;
        const generation = self.generation;
        self.mutex.unlock();

        const worker = std.Thread.spawn(.{}, asyncProbe, .{ self, allocator, worker_cwd, options, generation }) catch |err| {
            self.mutex.lock();
            self.clear(allocator);
            self.mutex.unlock();
            return err;
        };
        self.mutex.lock();
        self.worker = worker;
        self.mutex.unlock();

        return .{ .segment = stale_segment, .pending = true };
    }

    /// Prevent an L1 rendered-prompt cache hit from extending a Git result
    /// beyond its configured lifetime. The prior segment stays visible while
    /// a replacement probe runs, including when the TTL is zero.
    pub fn invalidateExpired(self: *Cache, cwd_path: []const u8, options: Options) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (!self.valid or self.cwd == null or !std.mem.eql(u8, self.cwd.?, cwd_path)) return;
        if (self.isReusable(cwd_path, options)) return;
        if (self.in_flight) return;
        self.generation +%= 1;
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
        self.active_pid = null;
        self.cwd = null;
        self.segment = null;
        self.options = .{};
        self.cached_at_ns = null;
    }

    fn isReusable(self: *const Cache, cwd_path: []const u8, options: Options) bool {
        if (!self.valid or self.cwd == null or !std.mem.eql(u8, self.cwd.?, cwd_path)) return false;
        if (!sameOptions(self.options, options) or options.cache_ttl_ms == 0) return false;
        const cached_at_ns = self.cached_at_ns orelse return false;
        const elapsed_ns = std.time.nanoTimestamp() - cached_at_ns;
        return elapsed_ns >= 0 and elapsed_ns < @as(i128, options.cache_ttl_ms) * std.time.ns_per_ms;
    }

    fn cancelForRenderChange(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) ?std.Thread {
        self.mutex.lock();
        defer self.mutex.unlock();

        if (!self.in_flight) return null;
        if (self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path) and sameOptions(self.options, options)) return null;

        self.generation += 1;
        if (self.active_pid) |pid| killProcessId(pid);
        self.active_pid = null;
        if (self.cwd) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.cwd = null;
        self.segment = null;
        self.options = .{};
        self.cached_at_ns = null;
        self.valid = false;
        self.in_flight = false;
        const worker = self.worker;
        self.worker = null;
        return worker;
    }

    fn cancelActiveProcess(self: *Cache) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.generation += 1;
        if (self.active_pid) |pid| killProcessId(pid);
        self.active_pid = null;
        self.in_flight = false;
    }

    fn registerChild(self: *Cache, generation: u64, pid: std.process.Child.Id) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.generation == generation) self.active_pid = pid;
    }

    fn clearChild(self: *Cache, generation: u64, pid: std.process.Child.Id) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.generation == generation and self.active_pid != null and self.active_pid.? == pid) {
            self.active_pid = null;
        }
    }

    fn cancelled(self: *Cache, generation: u64) bool {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.generation != generation;
    }
};

fn sameOptions(left: Options, right: Options) bool {
    return left.show_dirty == right.show_dirty and left.cache_ttl_ms == right.cache_ttl_ms;
}

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

fn asyncProbe(cache: *Cache, allocator: std.mem.Allocator, cwd_path: []u8, options: Options, generation: u64) void {
    defer allocator.free(cwd_path);
    const segment = probeCancellable(allocator, cache, generation, cwd_path, options) catch null;

    cache.mutex.lock();
    defer cache.mutex.unlock();
    if (cache.generation != generation or cache.cwd == null or !std.mem.eql(u8, cache.cwd.?, cwd_path)) {
        if (segment) |value| allocator.free(value);
        return;
    }
    if (cache.segment) |value| allocator.free(value);
    cache.segment = segment;
    cache.valid = true;
    cache.in_flight = false;
    cache.cached_at_ns = std.time.nanoTimestamp();
}

pub fn probe(allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) !?[]u8 {
    return probeCancellable(allocator, null, 0, cwd_path, options);
}

fn probeCancellable(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8, options: Options) !?[]u8 {
    if (try probeLibgit2(allocator, cwd_path, options)) |segment| return segment;

    const branch_result = runCommand(allocator, cache, generation, cwd_path, &.{ "git", "branch", "--show-current" }, 4096) catch return null;
    defer allocator.free(branch_result.stdout);
    defer allocator.free(branch_result.stderr);

    if (!exitedZero(branch_result.term)) return null;
    if (cache) |value| if (value.cancelled(generation)) return null;

    const branch = std.mem.trim(u8, branch_result.stdout, " \t\r\n");
    if (branch.len == 0) return null;

    const dirty = if (options.show_dirty) try isDirty(allocator, cache, generation, cwd_path) else false;
    const worktree_segment = worktreeSegmentAlloc(allocator, cwd_path) catch null;
    defer if (worktree_segment) |segment| allocator.free(segment);
    if (worktree_segment) |segment| {
        return try std.fmt.allocPrint(allocator, "git:{s}{s} {s}", .{ branch, if (dirty) "*" else "", segment });
    }
    return try std.fmt.allocPrint(allocator, "git:{s}{s}", .{ branch, if (dirty) "*" else "" });
}

fn probeLibgit2(allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) !?[]u8 {
    var snapshot = (try git_libgit2.readSnapshot(allocator, cwd_path)) orelse return null;
    defer snapshot.deinit(allocator);
    const branch = snapshot.branch orelse return null;
    const dirty = options.show_dirty and (snapshot.counts.staged > 0 or
        snapshot.counts.unstaged > 0 or
        snapshot.counts.untracked > 0 or
        snapshot.counts.conflicts > 0);
    const worktree_segment = worktreeSegmentAlloc(allocator, cwd_path) catch null;
    defer if (worktree_segment) |segment| allocator.free(segment);
    if (worktree_segment) |segment| {
        return try std.fmt.allocPrint(allocator, "git:{s}{s} {s}", .{ branch, if (dirty) "*" else "", segment });
    }
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

fn isDirty(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8) !bool {
    const status_result = runCommand(allocator, cache, generation, cwd_path, &.{ "git", "status", "--porcelain" }, 4096) catch return false;
    defer allocator.free(status_result.stdout);
    defer allocator.free(status_result.stderr);

    return exitedZero(status_result.term) and std.mem.trim(u8, status_result.stdout, " \t\r\n").len > 0;
}

fn worktreeSegmentAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    var detection = (try vcs_worktree.detect(allocator, cwd_path)) orelse return null;
    defer detection.deinit(allocator);
    return try vcs_worktree.renderAlloc(allocator, detection);
}

fn runCommand(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8, argv: []const []const u8, max_output_bytes: usize) !std.process.Child.RunResult {
    if (cache) |value| if (value.cancelled(generation)) return error.Cancelled;

    var child = std.process.Child.init(argv, allocator);
    child.stdin_behavior = .Ignore;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    child.cwd = cwd_path;
    child.expand_arg0 = .expand;

    var stdout: std.ArrayList(u8) = .empty;
    defer stdout.deinit(allocator);
    var stderr: std.ArrayList(u8) = .empty;
    defer stderr.deinit(allocator);

    try child.spawn();
    errdefer _ = child.kill() catch {};
    if (cache) |value| {
        value.registerChild(generation, child.id);
        if (value.cancelled(generation)) return error.Cancelled;
    }
    defer if (cache) |value| value.clearChild(generation, child.id);

    try child.collectOutput(allocator, &stdout, &stderr, max_output_bytes);
    return .{
        .stdout = try stdout.toOwnedSlice(allocator),
        .stderr = try stderr.toOwnedSlice(allocator),
        .term = try child.wait(),
    };
}

fn killProcessId(pid: std.process.Child.Id) void {
    switch (builtin.os.tag) {
        .windows => {},
        else => std.posix.kill(pid, std.posix.SIG.KILL) catch {},
    }
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
    try std.testing.expect(try cache.render(allocator, dir_path, .{}) == null);
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
    const rendered = (try cache.render(allocator, dir_path, .{})).?;
    defer allocator.free(rendered);
    try std.testing.expectEqualStrings("git:main*", rendered);

    const clean = (try cache.render(allocator, dir_path, .{ .show_dirty = false })).?;
    defer allocator.free(clean);
    try std.testing.expectEqualStrings("git:main", clean);
}

test "renders linked worktree name" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const tracked_file = try std.fmt.allocPrint(allocator, "{s}/tracked.txt", .{dir_path});
    defer allocator.free(tracked_file);
    var file = try std.fs.createFileAbsolute(tracked_file, .{});
    try file.writeAll("tracked");
    file.close();
    try runGit(allocator, dir_path, &.{ "git", "add", "tracked.txt" });
    try runGit(allocator, dir_path, &.{ "git", "-c", "user.name=shisa", "-c", "user.email=shisa@example.invalid", "commit", "-m", "init" });

    const linked_path = try std.fmt.allocPrint(allocator, "{s}-linked", .{dir_path});
    defer allocator.free(linked_path);
    defer std.fs.cwd().deleteTree(linked_path) catch {};
    try runGit(allocator, dir_path, &.{ "git", "worktree", "add", linked_path, "-b", "feature" });

    var cache = Cache{};
    defer cache.deinit(allocator);
    const rendered = (try cache.render(allocator, linked_path, .{})).?;
    defer allocator.free(rendered);
    const expected = try std.fmt.allocPrint(allocator, "git:feature wt:{s}", .{std.fs.path.basename(linked_path)});
    defer allocator.free(expected);
    try std.testing.expectEqualStrings(expected, rendered);
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
    const clean = (try cache.render(allocator, dir_path, .{})).?;
    defer allocator.free(clean);
    try std.testing.expectEqualStrings("git:main", clean);

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    const cached = (try cache.render(allocator, dir_path, .{})).?;
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("git:main", cached);

    cache.invalidate(allocator, dir_path);
    const refreshed = (try cache.render(allocator, dir_path, .{})).?;
    defer allocator.free(refreshed);
    try std.testing.expectEqualStrings("git:main*", refreshed);
}

test "zero TTL does not reuse a cached git segment" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{
        .valid = true,
        .cwd = try allocator.dupe(u8, dir_path),
        .segment = try allocator.dupe(u8, "git:stale"),
        .options = .{ .cache_ttl_ms = 250 },
        .cached_at_ns = std.time.nanoTimestamp(),
    };
    defer cache.deinit(allocator);

    var rendered = try cache.renderAsync(allocator, dir_path, .{ .cache_ttl_ms = 0 });
    defer rendered.deinit(allocator);
    try std.testing.expect(rendered.segment == null);
    try std.testing.expect(cache.valid);
    try std.testing.expect(cache.segment == null);
}

test "expired async result remains visible while it refreshes" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    var cache = Cache{};
    defer cache.deinit(allocator);
    const initial = (try cache.render(allocator, dir_path, .{ .cache_ttl_ms = 0 })).?;
    defer allocator.free(initial);
    cache.invalidateExpired(dir_path, .{ .cache_ttl_ms = 0 });

    var refreshed = try cache.renderAsync(allocator, dir_path, .{ .cache_ttl_ms = 0 });
    defer refreshed.deinit(allocator);
    try std.testing.expect(refreshed.pending);
    try std.testing.expectEqualStrings("git:main", refreshed.segment.?);
}

fn runSleepForCancelTest(cache: *Cache, allocator: std.mem.Allocator, term_out: *?std.process.Child.Term) void {
    const result = runCommand(allocator, cache, 1, "/tmp", &.{ "/bin/sleep", "10" }, 4096) catch return;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    term_out.* = result.term;
}

fn waitForActivePid(cache: *Cache) !void {
    for (0..100) |_| {
        cache.mutex.lock();
        const active = cache.active_pid != null;
        cache.mutex.unlock();
        if (active) return;
        std.Thread.sleep(10 * std.time.ns_per_ms);
    }
    return error.Timeout;
}

test "cancels active git child when cwd changes" {
    if (builtin.os.tag == .windows) return error.SkipZigTest;

    const allocator = std.testing.allocator;
    var cache = Cache{};
    defer cache.deinit(allocator);
    cache.cwd = try allocator.dupe(u8, "/old");
    cache.in_flight = true;
    cache.generation = 1;

    var term: ?std.process.Child.Term = null;
    const thread = try std.Thread.spawn(.{}, runSleepForCancelTest, .{ &cache, allocator, &term });
    try waitForActivePid(&cache);
    _ = cache.cancelForRenderChange(allocator, "/new", .{});
    thread.join();

    try std.testing.expect(term != null);
    try std.testing.expect(switch (term.?) {
        .Signal => true,
        else => false,
    });
    try std.testing.expect(!cache.in_flight);
    try std.testing.expect(cache.cwd == null);
}

test "git invalidation cancels active child" {
    if (builtin.os.tag == .windows) return error.SkipZigTest;

    const allocator = std.testing.allocator;
    var cache = Cache{};
    defer cache.deinit(allocator);
    cache.cwd = try allocator.dupe(u8, "/old");
    cache.in_flight = true;
    cache.generation = 1;

    var term: ?std.process.Child.Term = null;
    const thread = try std.Thread.spawn(.{}, runSleepForCancelTest, .{ &cache, allocator, &term });
    try waitForActivePid(&cache);
    cache.invalidate(allocator, "/old");
    thread.join();

    try std.testing.expect(term != null);
    try std.testing.expect(switch (term.?) {
        .Signal => true,
        else => false,
    });
    try std.testing.expect(!cache.in_flight);
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
    var first = try cache.renderAsync(allocator, dir_path, .{});
    defer first.deinit(allocator);
    try std.testing.expect(first.pending);
    try std.testing.expect(first.segment == null);

    for (0..100) |_| {
        var rendered = try cache.renderAsync(allocator, dir_path, .{});
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
    var rendered = try cache.renderAsync(allocator, dir_path, .{});
    defer rendered.deinit(allocator);
    try std.testing.expect(!rendered.pending);
    try std.testing.expect(rendered.segment == null);
}
