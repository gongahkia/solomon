const std = @import("std");
const builtin = @import("builtin");

pub const Options = struct {
    python: bool = true,
    node: bool = true,
    rust: bool = true,
    go: bool = true,
};

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    valid: bool = false,
    in_flight: bool = false,
    generation: u64 = 0,
    active_pid: ?std.process.Child.Id = null,
    cwd: ?[]u8 = null,
    env_hash: ?[]u8 = null,
    segment: ?[]u8 = null,
    options: Options = .{},
    worker: ?std.Thread = null,

    pub const AsyncRender = struct {
        segment: ?[]u8 = null,
        pending: bool = false,

        pub fn deinit(self: *AsyncRender, allocator: std.mem.Allocator) void {
            if (self.segment) |segment| allocator.free(segment);
            self.* = .{};
        }
    };

    pub fn deinit(self: *Cache, allocator: std.mem.Allocator) void {
        self.cancelActiveProcess();
        const worker = self.takeWorker();
        if (worker) |thread| thread.join();
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clear(allocator);
    }

    pub fn renderAsync(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8, env_hash: ?[]const u8, path_env: ?[]const u8, options: Options) !AsyncRender {
        self.joinFinishedWorker();

        const cancelled_worker = self.cancelForRenderChange(allocator, cwd_path, env_hash, options);
        if (cancelled_worker) |thread| thread.join();

        self.mutex.lock();
        if (self.isReusable(cwd_path, env_hash, options)) {
            const segment = if (self.segment) |value| try allocator.dupe(u8, value) else null;
            self.mutex.unlock();
            return .{ .segment = segment };
        }
        if (self.in_flight) {
            self.mutex.unlock();
            return .{ .pending = true };
        }
        self.mutex.unlock();

        if (!(try detect(allocator, cwd_path, options)).any()) {
            self.mutex.lock();
            defer self.mutex.unlock();
            self.clear(allocator);
            self.valid = true;
            self.cwd = try allocator.dupe(u8, cwd_path);
            self.env_hash = if (env_hash) |value| try allocator.dupe(u8, value) else null;
            self.options = options;
            return .{};
        }

        const worker_cwd = try allocator.dupe(u8, cwd_path);
        errdefer allocator.free(worker_cwd);
        const worker_path_env = if (path_env) |value| try allocator.dupe(u8, value) else null;
        errdefer if (worker_path_env) |value| allocator.free(value);

        self.mutex.lock();
        self.clear(allocator);
        self.cwd = try allocator.dupe(u8, cwd_path);
        self.env_hash = if (env_hash) |value| try allocator.dupe(u8, value) else null;
        self.options = options;
        self.in_flight = true;
        self.generation += 1;
        const generation = self.generation;
        self.mutex.unlock();

        const worker = std.Thread.spawn(.{}, asyncProbe, .{ self, allocator, worker_cwd, worker_path_env, options, generation }) catch |err| {
            self.mutex.lock();
            self.clear(allocator);
            self.mutex.unlock();
            if (worker_path_env) |value| allocator.free(value);
            return err;
        };
        self.mutex.lock();
        self.worker = worker;
        self.mutex.unlock();

        return .{ .pending = true };
    }

    fn isReusable(self: *const Cache, cwd_path: []const u8, env_hash: ?[]const u8, options: Options) bool {
        return self.valid and self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path) and optionalEql(self.env_hash, env_hash) and sameOptions(self.options, options);
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
        if (self.env_hash) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.valid = false;
        self.in_flight = false;
        self.active_pid = null;
        self.cwd = null;
        self.env_hash = null;
        self.segment = null;
        self.options = .{};
    }

    fn cancelForRenderChange(self: *Cache, allocator: std.mem.Allocator, cwd_path: []const u8, env_hash: ?[]const u8, options: Options) ?std.Thread {
        self.mutex.lock();
        defer self.mutex.unlock();

        if (!self.in_flight) return null;
        if (self.cwd != null and std.mem.eql(u8, self.cwd.?, cwd_path) and optionalEql(self.env_hash, env_hash) and sameOptions(self.options, options)) return null;

        self.generation += 1;
        if (self.active_pid) |pid| killProcessId(pid);
        self.active_pid = null;
        if (self.cwd) |value| allocator.free(value);
        if (self.env_hash) |value| allocator.free(value);
        if (self.segment) |value| allocator.free(value);
        self.cwd = null;
        self.env_hash = null;
        self.segment = null;
        self.options = .{};
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
    return left.python == right.python and left.node == right.node and left.rust == right.rust and left.go == right.go;
}

fn optionalEql(left: ?[]const u8, right: ?[]const u8) bool {
    if (left) |left_value| {
        return if (right) |right_value| std.mem.eql(u8, left_value, right_value) else false;
    }
    return right == null;
}

const Detection = struct {
    python: bool = false,
    node: bool = false,
    rust: bool = false,
    go: bool = false,

    fn any(self: Detection) bool {
        return self.python or self.node or self.rust or self.go;
    }
};

const Versions = struct {
    python: ?[]const u8 = null,
    node: ?[]const u8 = null,
    rust: ?[]const u8 = null,
    go: ?[]const u8 = null,

    fn any(self: Versions) bool {
        return self.python != null or self.node != null or self.rust != null or self.go != null;
    }
};

fn asyncProbe(cache: *Cache, allocator: std.mem.Allocator, cwd_path: []u8, path_env: ?[]u8, options: Options, generation: u64) void {
    defer allocator.free(cwd_path);
    defer if (path_env) |value| allocator.free(value);
    const segment = probeCancellable(allocator, cache, generation, cwd_path, path_env, options) catch null;

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
}

pub fn probe(allocator: std.mem.Allocator, cwd_path: []const u8, path_env: ?[]const u8, options: Options) !?[]u8 {
    return probeCancellable(allocator, null, 0, cwd_path, path_env, options);
}

fn probeCancellable(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8, path_env: ?[]const u8, options: Options) !?[]u8 {
    const detected = try detect(allocator, cwd_path, options);
    if (!detected.any()) return null;

    var versions = Versions{};
    if (detected.python) versions.python = try commandVersion(allocator, cache, generation, cwd_path, path_env, &.{ "python3", "--version" }, .python);
    defer if (versions.python) |value| allocator.free(value);
    if (cache) |value| if (value.cancelled(generation)) return null;
    if (detected.node) versions.node = try commandVersion(allocator, cache, generation, cwd_path, path_env, &.{ "node", "--version" }, .node);
    defer if (versions.node) |value| allocator.free(value);
    if (cache) |value| if (value.cancelled(generation)) return null;
    if (detected.rust) versions.rust = try commandVersion(allocator, cache, generation, cwd_path, path_env, &.{ "rustc", "--version" }, .rust);
    defer if (versions.rust) |value| allocator.free(value);
    if (cache) |value| if (value.cancelled(generation)) return null;
    if (detected.go) versions.go = try commandVersion(allocator, cache, generation, cwd_path, path_env, &.{ "go", "version" }, .go);
    defer if (versions.go) |value| allocator.free(value);

    if (!versions.any()) return null;
    return try formatVersions(allocator, versions);
}

fn detect(allocator: std.mem.Allocator, cwd_path: []const u8, options: Options) !Detection {
    return .{
        .python = options.python and try hasAncestorMarker(allocator, cwd_path, &.{ "pyproject.toml", "requirements.txt", "setup.py" }),
        .node = options.node and try hasAncestorMarker(allocator, cwd_path, &.{"package.json"}),
        .rust = options.rust and try hasAncestorMarker(allocator, cwd_path, &.{"Cargo.toml"}),
        .go = options.go and try hasAncestorMarker(allocator, cwd_path, &.{"go.mod"}),
    };
}

fn hasAncestorMarker(allocator: std.mem.Allocator, cwd_path: []const u8, markers: []const []const u8) !bool {
    var current = try allocator.dupe(u8, cwd_path);
    defer allocator.free(current);

    while (current.len > 0) {
        for (markers) |marker| {
            const path = try std.fs.path.join(allocator, &.{ current, marker });
            const found = found: {
                std.fs.cwd().access(path, .{}) catch |err| switch (err) {
                    error.FileNotFound => break :found false,
                    else => {
                        allocator.free(path);
                        return err;
                    },
                };
                break :found true;
            };
            allocator.free(path);
            if (found) return true;
        }

        const parent = std.fs.path.dirname(current) orelse break;
        if (std.mem.eql(u8, parent, current)) break;
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }

    return false;
}

const VersionKind = enum {
    python,
    node,
    rust,
    go,
};

fn commandVersion(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8, path_env: ?[]const u8, argv: []const []const u8, kind: VersionKind) !?[]u8 {
    const result = runCommand(allocator, cache, generation, cwd_path, path_env, argv, 4096) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;
    if (cache) |value| if (value.cancelled(generation)) return null;

    const raw = if (result.stdout.len > 0) result.stdout else result.stderr;
    const trimmed = std.mem.trim(u8, raw, " \t\r\n");
    if (trimmed.len == 0) return null;

    return switch (kind) {
        .python => tokenAfterPrefix(allocator, trimmed, "Python "),
        .node => try allocator.dupe(u8, trimmed),
        .rust => secondToken(allocator, trimmed),
        .go => goVersion(allocator, trimmed),
    };
}

fn runCommand(allocator: std.mem.Allocator, cache: ?*Cache, generation: u64, cwd_path: []const u8, path_env: ?[]const u8, argv: []const []const u8, max_output_bytes: usize) !std.process.Child.RunResult {
    if (cache) |value| if (value.cancelled(generation)) return error.Cancelled;

    const resolved_arg0 = if (path_env) |value| try resolveArg0InPathAlloc(allocator, value, argv[0]) else null;
    defer if (resolved_arg0) |value| allocator.free(value);
    const child_argv = if (resolved_arg0) |value| argv: {
        const copied = try allocator.alloc([]const u8, argv.len);
        copied[0] = value;
        @memcpy(copied[1..], argv[1..]);
        break :argv copied;
    } else argv;
    defer if (resolved_arg0 != null) allocator.free(child_argv);

    var child = std.process.Child.init(child_argv, allocator);
    child.stdin_behavior = .Ignore;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    child.cwd = cwd_path;
    child.expand_arg0 = if (resolved_arg0 == null) .expand else .no_expand;
    var env_map_storage: std.process.EnvMap = undefined;
    var has_env_map = false;
    defer if (has_env_map) env_map_storage.deinit();
    if (path_env) |value| {
        env_map_storage = try std.process.getEnvMap(allocator);
        has_env_map = true;
        try env_map_storage.put("PATH", value);
        child.env_map = &env_map_storage;
    }

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

fn resolveArg0InPathAlloc(allocator: std.mem.Allocator, path_env: []const u8, arg0: []const u8) !?[]u8 {
    if (std.mem.indexOfScalar(u8, arg0, '/') != null) return null;
    var paths = std.mem.splitScalar(u8, path_env, ':');
    while (paths.next()) |dir| {
        if (dir.len == 0) continue;
        const candidate = try std.fs.path.join(allocator, &.{ dir, arg0 });
        std.fs.cwd().access(candidate, .{}) catch {
            allocator.free(candidate);
            continue;
        };
        return candidate;
    }
    return null;
}

fn killProcessId(pid: std.process.Child.Id) void {
    switch (builtin.os.tag) {
        .windows => {},
        else => std.posix.kill(pid, std.posix.SIG.KILL) catch {},
    }
}

fn tokenAfterPrefix(allocator: std.mem.Allocator, value: []const u8, prefix: []const u8) !?[]u8 {
    if (!std.mem.startsWith(u8, value, prefix)) return null;
    return firstToken(allocator, value[prefix.len..]);
}

fn firstToken(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    var it = std.mem.tokenizeAny(u8, value, " \t\r\n");
    const token = it.next() orelse return null;
    return try allocator.dupe(u8, token);
}

fn secondToken(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    var it = std.mem.tokenizeAny(u8, value, " \t\r\n");
    _ = it.next() orelse return null;
    const token = it.next() orelse return null;
    return try allocator.dupe(u8, token);
}

fn goVersion(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    var it = std.mem.tokenizeAny(u8, value, " \t\r\n");
    _ = it.next() orelse return null;
    _ = it.next() orelse return null;
    const token = it.next() orelse return null;
    if (std.mem.startsWith(u8, token, "go")) return try allocator.dupe(u8, token[2..]);
    return try allocator.dupe(u8, token);
}

fn formatVersions(allocator: std.mem.Allocator, versions: Versions) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "lang:");
    var wrote = false;
    if (versions.python) |value| try appendVersion(allocator, &out, &wrote, "py", value);
    if (versions.node) |value| try appendVersion(allocator, &out, &wrote, "node", value);
    if (versions.rust) |value| try appendVersion(allocator, &out, &wrote, "rust", value);
    if (versions.go) |value| try appendVersion(allocator, &out, &wrote, "go", value);
    return out.toOwnedSlice(allocator);
}

fn appendVersion(allocator: std.mem.Allocator, out: *std.ArrayList(u8), wrote: *bool, name: []const u8, value: []const u8) !void {
    if (wrote.*) try out.append(allocator, ',');
    try out.appendSlice(allocator, name);
    try out.append(allocator, ':');
    try out.appendSlice(allocator, value);
    wrote.* = true;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "detects project markers in ancestors" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    const marker = try std.fmt.allocPrint(allocator, "{s}/pyproject.toml", .{dir_path});
    defer allocator.free(marker);
    var file = try std.fs.createFileAbsolute(marker, .{});
    file.close();

    const detected = try detect(allocator, nested);
    try std.testing.expect(detected.python);
    try std.testing.expect(!detected.node);
}

test "formats version segment" {
    const rendered = try formatVersions(std.testing.allocator, .{
        .python = "3.11.0",
        .node = "v20.0.0",
        .rust = "1.75.0",
        .go = "1.22.0",
    });
    defer std.testing.allocator.free(rendered);
    try std.testing.expectEqualStrings("lang:py:3.11.0,node:v20.0.0,rust:1.75.0,go:1.22.0", rendered);
}

test "probe uses request path env for language commands" {
    if (builtin.os.tag == .windows) return error.SkipZigTest;

    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-path-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const bin_path = try std.fmt.allocPrint(allocator, "{s}/bin", .{dir_path});
    defer allocator.free(bin_path);
    const repo_path = try std.fmt.allocPrint(allocator, "{s}/repo", .{dir_path});
    defer allocator.free(repo_path);
    try std.fs.cwd().makePath(bin_path);
    try std.fs.cwd().makePath(repo_path);

    const marker = try std.fmt.allocPrint(allocator, "{s}/pyproject.toml", .{repo_path});
    defer allocator.free(marker);
    {
        var file = try std.fs.createFileAbsolute(marker, .{});
        defer file.close();
    }
    const python_path = try std.fmt.allocPrint(allocator, "{s}/python3", .{bin_path});
    defer allocator.free(python_path);
    {
        var file = try std.fs.createFileAbsolute(python_path, .{ .mode = 0o755 });
        defer file.close();
        try file.writeAll("#!/bin/sh\necho Python 9.9.9\n");
        try file.chmod(0o755);
    }

    const rendered = (try probe(allocator, repo_path, bin_path)).?;
    defer allocator.free(rendered);
    try std.testing.expectEqualStrings("lang:py:9.9.9", rendered);
}

test "async render hides non project cwd without pending" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{};
    defer cache.deinit(allocator);
    var rendered = try cache.renderAsync(allocator, dir_path, null, null);
    defer rendered.deinit(allocator);
    try std.testing.expect(!rendered.pending);
    try std.testing.expect(rendered.segment == null);
}

test "async cache invalidates when env hash changes" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-env-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    var cache = Cache{
        .valid = true,
        .cwd = try allocator.dupe(u8, dir_path),
        .env_hash = try allocator.dupe(u8, "outer"),
        .segment = try allocator.dupe(u8, "lang:py:3.10.0"),
    };
    defer cache.deinit(allocator);

    var rendered = try cache.renderAsync(allocator, dir_path, "inner", null);
    defer rendered.deinit(allocator);
    try std.testing.expect(!rendered.pending);
    try std.testing.expect(rendered.segment == null);
    try std.testing.expect(cache.valid);
    try std.testing.expectEqualStrings("inner", cache.env_hash.?);
    try std.testing.expect(cache.segment == null);
}

fn runSleepForCancelTest(cache: *Cache, allocator: std.mem.Allocator, term_out: *?std.process.Child.Term) void {
    const result = runCommand(allocator, cache, 1, "/tmp", null, &.{ "/bin/sleep", "10" }, 4096) catch return;
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

test "cancels active language child when cwd changes" {
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
    _ = cache.cancelForCwdOrEnvChange(allocator, "/new", null);
    thread.join();

    try std.testing.expect(term != null);
    try std.testing.expect(switch (term.?) {
        .Signal => true,
        else => false,
    });
    try std.testing.expect(!cache.in_flight);
    try std.testing.expect(cache.cwd == null);
}

test "async render fills python marker when python3 exists" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker = try std.fmt.allocPrint(allocator, "{s}/pyproject.toml", .{dir_path});
    defer allocator.free(marker);
    var file = try std.fs.createFileAbsolute(marker, .{});
    file.close();

    const python = try commandVersion(allocator, null, 0, dir_path, null, &.{ "python3", "--version" }, .python);
    if (python) |value| allocator.free(value) else return;

    var cache = Cache{};
    defer cache.deinit(allocator);
    var first = try cache.renderAsync(allocator, dir_path, null, null);
    defer first.deinit(allocator);
    try std.testing.expect(first.pending);

    for (0..100) |_| {
        var rendered = try cache.renderAsync(allocator, dir_path, null, null);
        defer rendered.deinit(allocator);
        if (rendered.segment) |segment| {
            try std.testing.expect(std.mem.startsWith(u8, segment, "lang:py:"));
            return;
        }
        std.Thread.sleep(10 * std.time.ns_per_ms);
    }
    return error.Timeout;
}
