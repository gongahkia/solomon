const std = @import("std");
const builtin = @import("builtin");
const client = @import("shisa-client.zig");
const paths = @import("daemon/paths.zig");

const Config = struct {
    daemon_path: ?[]const u8 = null,
    socket_path: ?[]const u8 = null,
    max_restarts: ?u32 = null,
    backoff_ms: u64 = 100,
    max_backoff_ms: u64 = 5000,
    heartbeat_ms: u64 = 1000,
};

const ParseError = error{
    InvalidNumber,
    MissingValue,
    UnknownArgument,
};

const heartbeat_miss_limit = 3;
const heartbeat_request = "{\"v\":1,\"op\":\"health\",\"request_id\":\"supervisor-heartbeat\"}";

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parse(args);
    const default_daemon_path = if (config.daemon_path == null) try siblingDaemonPath(allocator) else null;
    defer if (default_daemon_path) |path| allocator.free(path);

    const daemon_path = config.daemon_path orelse default_daemon_path.?;
    try supervise(allocator, daemon_path, config);
}

fn supervise(allocator: std.mem.Allocator, daemon_path: []const u8, config: Config) !void {
    const default_socket_path = if (config.socket_path == null) try paths.defaultSocketPath(allocator) else null;
    defer if (default_socket_path) |path| allocator.free(path);
    const heartbeat_socket_path = config.socket_path orelse default_socket_path.?;

    var restarts: u32 = 0;
    var backoff_ms = config.backoff_ms;

    while (true) {
        var child = try spawnDaemon(allocator, daemon_path, config.socket_path);
        const term = try monitorDaemon(allocator, &child, heartbeat_socket_path, config.heartbeat_ms);
        if (cleanExit(term)) return;

        if (config.max_restarts) |max_restarts| {
            if (restarts >= max_restarts) return error.SupervisorRestartLimit;
        }
        restarts += 1;

        std.Thread.sleep(backoff_ms * std.time.ns_per_ms);
        backoff_ms = nextBackoffMs(backoff_ms, config.max_backoff_ms);
    }
}

fn nextBackoffMs(current: u64, cap: u64) u64 {
    if (current >= cap) return cap;
    if (current > std.math.maxInt(u64) / 2) return cap;
    return @min(current * 2, cap);
}

fn spawnDaemon(allocator: std.mem.Allocator, daemon_path: []const u8, socket_path: ?[]const u8) !std.process.Child {
    var child = if (socket_path) |path| child: {
        const argv = [_][]const u8{ daemon_path, "--foreground", "--socket", path };
        break :child std.process.Child.init(argv[0..], allocator);
    } else child: {
        const argv = [_][]const u8{ daemon_path, "--foreground" };
        break :child std.process.Child.init(argv[0..], allocator);
    };

    child.stdin_behavior = .Ignore;
    child.stdout_behavior = .Inherit;
    child.stderr_behavior = .Inherit;
    try child.spawn();
    try child.waitForSpawn();
    return child;
}

fn monitorDaemon(allocator: std.mem.Allocator, child: *std.process.Child, socket_path: []const u8, heartbeat_ms: u64) !std.process.Child.Term {
    var misses: u8 = 0;
    while (true) {
        if (pollChildTerm(child)) |term| return term;
        std.Thread.sleep(heartbeat_ms * std.time.ns_per_ms);
        if (pollChildTerm(child)) |term| return term;
        if (try heartbeatOk(allocator, socket_path)) {
            misses = 0;
            continue;
        }
        misses += 1;
        if (misses >= heartbeat_miss_limit) {
            return child.kill() catch |err| switch (err) {
                error.AlreadyTerminated => std.process.Child.Term{ .Unknown = 0 },
                else => return err,
            };
        }
    }
}

fn heartbeatOk(allocator: std.mem.Allocator, socket_path: []const u8) !bool {
    const response = client.requestAlloc(allocator, socket_path, heartbeat_request) catch return false;
    defer allocator.free(response);
    return heartbeatResponseOk(allocator, response);
}

fn heartbeatResponseOk(allocator: std.mem.Allocator, response: []const u8) !bool {
    if (std.mem.eql(u8, response, "ok\n")) return true;
    const HealthResponse = struct {
        ok: bool = false,
    };
    var parsed = std.json.parseFromSlice(HealthResponse, allocator, response, .{ .ignore_unknown_fields = true }) catch return false;
    defer parsed.deinit();
    return parsed.value.ok;
}

fn pollChildTerm(child: *std.process.Child) ?std.process.Child.Term {
    return switch (builtin.os.tag) {
        .linux, .macos => pollChildTermPosix(child),
        else => null,
    };
}

fn pollChildTermPosix(child: *std.process.Child) ?std.process.Child.Term {
    const result = std.posix.waitpid(child.id, std.posix.W.NOHANG);
    if (result.pid == 0) return null;
    return statusToTerm(result.status);
}

fn statusToTerm(status: u32) std.process.Child.Term {
    return if (std.posix.W.IFEXITED(status))
        std.process.Child.Term{ .Exited = std.posix.W.EXITSTATUS(status) }
    else if (std.posix.W.IFSIGNALED(status))
        std.process.Child.Term{ .Signal = std.posix.W.TERMSIG(status) }
    else if (std.posix.W.IFSTOPPED(status))
        std.process.Child.Term{ .Stopped = std.posix.W.STOPSIG(status) }
    else
        std.process.Child.Term{ .Unknown = status };
}

fn cleanExit(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

fn siblingDaemonPath(allocator: std.mem.Allocator) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse ".";
    return std.fs.path.join(allocator, &.{ dir, "shisad" });
}

fn parse(args: []const []const u8) ParseError!Config {
    var config = Config{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--daemon")) {
            config.daemon_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--max-restarts")) {
            config.max_restarts = try parseU32(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--backoff-ms")) {
            config.backoff_ms = try parseU64(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--max-backoff-ms")) {
            config.max_backoff_ms = try parseU64(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--heartbeat-ms")) {
            config.heartbeat_ms = try parseU64(try nextValue(args, &i));
        } else {
            return error.UnknownArgument;
        }
    }

    if (config.heartbeat_ms == 0) return error.InvalidNumber;
    return config;
}

fn nextValue(args: []const []const u8, index: *usize) ParseError![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

fn parseU32(value: []const u8) ParseError!u32 {
    return std.fmt.parseInt(u32, value, 10) catch error.InvalidNumber;
}

fn parseU64(value: []const u8) ParseError!u64 {
    return std.fmt.parseInt(u64, value, 10) catch error.InvalidNumber;
}

test "parses supervisor options" {
    const args = [_][]const u8{
        "--daemon",
        "/tmp/shisad",
        "--socket",
        "/tmp/shisa.sock",
        "--max-restarts",
        "3",
        "--backoff-ms",
        "25",
        "--max-backoff-ms",
        "100",
        "--heartbeat-ms",
        "50",
    };
    const config = try parse(args[0..]);
    try std.testing.expectEqualStrings("/tmp/shisad", config.daemon_path.?);
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
    try std.testing.expectEqual(@as(u32, 3), config.max_restarts.?);
    try std.testing.expectEqual(@as(u64, 25), config.backoff_ms);
    try std.testing.expectEqual(@as(u64, 100), config.max_backoff_ms);
    try std.testing.expectEqual(@as(u64, 50), config.heartbeat_ms);
}

test "rejects malformed restart count" {
    const args = [_][]const u8{ "--max-restarts", "x" };
    try std.testing.expectError(error.InvalidNumber, parse(args[0..]));
}

test "rejects zero heartbeat interval" {
    const args = [_][]const u8{ "--heartbeat-ms", "0" };
    try std.testing.expectError(error.InvalidNumber, parse(args[0..]));
}

test "backoff doubles up to cap" {
    try std.testing.expectEqual(@as(u64, 200), nextBackoffMs(100, 5000));
    try std.testing.expectEqual(@as(u64, 5000), nextBackoffMs(4000, 5000));
    try std.testing.expectEqual(@as(u64, 5000), nextBackoffMs(std.math.maxInt(u64), 5000));
}

test "heartbeat response accepts legacy and JSON health" {
    try std.testing.expect(try heartbeatResponseOk(std.testing.allocator, "ok\n"));
    try std.testing.expect(try heartbeatResponseOk(std.testing.allocator, "{\"v\":1,\"ok\":true}"));
    try std.testing.expect(!(try heartbeatResponseOk(std.testing.allocator, "{\"v\":1,\"ok\":false}")));
    try std.testing.expect(!(try heartbeatResponseOk(std.testing.allocator, "bad\n")));
}
