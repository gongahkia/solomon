const std = @import("std");

pub const Cache = struct {
    mutex: std.Thread.Mutex = .{},
    valid: bool = false,
    in_flight: bool = false,
    cwd: ?[]u8 = null,
    segment: ?[]u8 = null,
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
        const worker = self.takeWorker();
        if (worker) |thread| thread.join();
        self.mutex.lock();
        defer self.mutex.unlock();
        self.clear(allocator);
    }

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

        if (!(try detect(allocator, cwd_path)).any()) {
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
        self.mutex.unlock();

        const worker = std.Thread.spawn(.{}, asyncProbe, .{ self, allocator, worker_cwd }) catch |err| {
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

fn asyncProbe(cache: *Cache, allocator: std.mem.Allocator, cwd_path: []u8) void {
    defer allocator.free(cwd_path);
    const segment = probe(allocator, cwd_path) catch null;

    cache.mutex.lock();
    defer cache.mutex.unlock();
    if (cache.segment) |value| allocator.free(value);
    cache.segment = segment;
    cache.valid = true;
    cache.in_flight = false;
}

pub fn probe(allocator: std.mem.Allocator, cwd_path: []const u8) !?[]u8 {
    const detected = try detect(allocator, cwd_path);
    if (!detected.any()) return null;

    var versions = Versions{};
    if (detected.python) versions.python = try commandVersion(allocator, cwd_path, &.{ "python3", "--version" }, .python);
    defer if (versions.python) |value| allocator.free(value);
    if (detected.node) versions.node = try commandVersion(allocator, cwd_path, &.{ "node", "--version" }, .node);
    defer if (versions.node) |value| allocator.free(value);
    if (detected.rust) versions.rust = try commandVersion(allocator, cwd_path, &.{ "rustc", "--version" }, .rust);
    defer if (versions.rust) |value| allocator.free(value);
    if (detected.go) versions.go = try commandVersion(allocator, cwd_path, &.{ "go", "version" }, .go);
    defer if (versions.go) |value| allocator.free(value);

    if (!versions.any()) return null;
    return try formatVersions(allocator, versions);
}

fn detect(allocator: std.mem.Allocator, cwd_path: []const u8) !Detection {
    return .{
        .python = try hasAncestorMarker(allocator, cwd_path, &.{ "pyproject.toml", "requirements.txt", "setup.py" }),
        .node = try hasAncestorMarker(allocator, cwd_path, &.{"package.json"}),
        .rust = try hasAncestorMarker(allocator, cwd_path, &.{"Cargo.toml"}),
        .go = try hasAncestorMarker(allocator, cwd_path, &.{"go.mod"}),
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

fn commandVersion(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8, kind: VersionKind) !?[]u8 {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return null;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return null;

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

test "async render hides non project cwd without pending" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lang-{x}", .{std.crypto.random.int(u64)});
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

    const python = try commandVersion(allocator, dir_path, &.{ "python3", "--version" }, .python);
    if (python) |value| allocator.free(value) else return;

    var cache = Cache{};
    defer cache.deinit(allocator);
    var first = try cache.renderAsync(allocator, dir_path);
    defer first.deinit(allocator);
    try std.testing.expect(first.pending);

    for (0..100) |_| {
        var rendered = try cache.renderAsync(allocator, dir_path);
        defer rendered.deinit(allocator);
        if (rendered.segment) |segment| {
            try std.testing.expect(std.mem.startsWith(u8, segment, "lang:py:"));
            return;
        }
        std.Thread.sleep(10 * std.time.ns_per_ms);
    }
    return error.Timeout;
}
