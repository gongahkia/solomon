const std = @import("std");
const builtin = @import("builtin");
const client = @import("shisa-client.zig");
const paths = @import("daemon/paths.zig");
const win = std.os.windows;

const Config = struct {
    daemon_path: ?[]const u8 = null,
    socket_path: ?[]const u8 = null,
    self_disable_state_path: ?[]const u8 = null,
    max_restarts: ?u32 = null,
    backoff_ms: u64 = 100,
    max_backoff_ms: u64 = 5000,
    heartbeat_ms: u64 = 1000,
    self_disable: bool = true,
    reset_disable: bool = false,
};

const ParseError = error{
    InvalidNumber,
    MissingValue,
    UnknownArgument,
};

const heartbeat_miss_limit = 3;
const heartbeat_request = "{\"v\":1,\"op\":\"health\",\"request_id\":\"supervisor-heartbeat\"}";
const self_disable_window_seconds: i64 = 60;
const self_disable_crash_limit: u32 = 3;
var windows_job_handle: ?win.HANDLE = null;

extern "kernel32" fn CreateJobObjectW(lpJobAttributes: ?*const win.SECURITY_ATTRIBUTES, lpName: ?win.LPCWSTR) callconv(.winapi) win.HANDLE;
extern "kernel32" fn AssignProcessToJobObject(hJob: win.HANDLE, hProcess: win.HANDLE) callconv(.winapi) win.BOOL;
extern "kernel32" fn ResumeThread(hThread: win.HANDLE) callconv(.winapi) win.DWORD;

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parse(args);
    const default_daemon_path = if (config.daemon_path == null) try siblingDaemonPath(allocator) else null;
    defer if (default_daemon_path) |path| allocator.free(path);

    const default_state_path = if (config.self_disable and config.self_disable_state_path == null) try defaultSelfDisableStatePath(allocator) else null;
    defer if (default_state_path) |path| allocator.free(path);
    const self_disable_state_path = config.self_disable_state_path orelse default_state_path;

    if (config.reset_disable) {
        if (self_disable_state_path) |path| try clearSelfDisableState(allocator, path);
        return;
    }

    var active_path: ?[]u8 = null;
    defer if (active_path) |path| allocator.free(path);
    if (self_disable_state_path) |path| {
        active_path = try selfDisableActivePathAlloc(allocator, path);
        if (try enterSelfDisableGuard(allocator, path, active_path.?)) {
            try std.fs.File.stderr().writeAll("shisa-supervisor: disabled after repeated supervisor crashes; run with --reset-disable to re-enable\n");
            return;
        }
    }
    defer if (active_path) |path| std.fs.cwd().deleteFile(path) catch {};

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

fn heartbeatKillDelayMs(heartbeat_ms: u64) u64 {
    if (heartbeat_ms > std.math.maxInt(u64) / heartbeat_miss_limit) return std.math.maxInt(u64);
    return heartbeat_ms * heartbeat_miss_limit;
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
    prepareWindowsSpawn(&child);
    try child.spawn();
    errdefer _ = child.kill() catch {};
    try child.waitForSpawn();
    try finishWindowsSpawn(&child);
    return child;
}

fn prepareWindowsSpawn(child: *std.process.Child) void {
    if (builtin.os.tag == .windows) child.start_suspended = true;
}

fn finishWindowsSpawn(child: *std.process.Child) !void {
    if (builtin.os.tag != .windows) return;
    try assignChildToWindowsJob(child.id);
    try resumeWindowsThread(child.thread_handle);
}

fn assignChildToWindowsJob(process_handle: win.HANDLE) !void {
    const job = if (windows_job_handle) |handle| handle else job: {
        const handle = CreateJobObjectW(null, null);
        if (@intFromPtr(handle) == 0) return error.CreateJobObjectFailed;
        windows_job_handle = handle;
        break :job handle;
    };
    if (AssignProcessToJobObject(job, process_handle) == 0) return error.AssignProcessToJobObjectFailed;
}

fn resumeWindowsThread(thread_handle: win.HANDLE) !void {
    if (ResumeThread(thread_handle) == std.math.maxInt(win.DWORD)) return error.ResumeThreadFailed;
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
        .windows => pollChildTermWindows(child),
        .linux, .macos => pollChildTermPosix(child),
        else => null,
    };
}

fn pollChildTermWindows(child: *std.process.Child) ?std.process.Child.Term {
    if (builtin.os.tag != .windows) unreachable;
    std.os.windows.WaitForSingleObject(child.id, 0) catch |err| switch (err) {
        error.WaitTimeOut => return null,
        else => return .{ .Unknown = 1 },
    };
    return child.wait() catch .{ .Unknown = 1 };
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

fn enterSelfDisableGuard(allocator: std.mem.Allocator, state_path: []const u8, active_path: []const u8) !bool {
    const disabled_path = try selfDisableDisabledPathAlloc(allocator, state_path);
    defer allocator.free(disabled_path);

    if (pathExists(disabled_path)) return true;
    const now = std.time.timestamp();
    if (pathExists(active_path)) {
        var state = try readSelfDisableState(allocator, state_path);
        if (state.first_crash_ts == 0 or now - state.first_crash_ts > self_disable_window_seconds) {
            state.first_crash_ts = now;
            state.crashes = 1;
        } else {
            state.crashes += 1;
        }
        try writeSelfDisableState(allocator, state_path, state);
        if (state.crashes >= self_disable_crash_limit) {
            try writeTextFile(disabled_path, "disabled after repeated supervisor crashes\n");
            return true;
        }
    }
    try writeTextFile(active_path, "active\n");
    return false;
}

const SelfDisableState = struct {
    first_crash_ts: i64 = 0,
    crashes: u32 = 0,
};

fn readSelfDisableState(allocator: std.mem.Allocator, state_path: []const u8) !SelfDisableState {
    const data = std.fs.cwd().readFileAlloc(allocator, state_path, 4096) catch |err| switch (err) {
        error.FileNotFound => return .{},
        else => return err,
    };
    defer allocator.free(data);
    var it = std.mem.tokenizeAny(u8, data, " \t\r\n");
    const first_raw = it.next() orelse return .{};
    const count_raw = it.next() orelse return .{};
    return .{
        .first_crash_ts = std.fmt.parseInt(i64, first_raw, 10) catch 0,
        .crashes = std.fmt.parseInt(u32, count_raw, 10) catch 0,
    };
}

fn writeSelfDisableState(allocator: std.mem.Allocator, state_path: []const u8, state: SelfDisableState) !void {
    const data = try std.fmt.allocPrint(allocator, "{d} {d}\n", .{ state.first_crash_ts, state.crashes });
    defer allocator.free(data);
    try writeTextFile(state_path, data);
}

fn clearSelfDisableState(allocator: std.mem.Allocator, state_path: []const u8) !void {
    const active_path = try selfDisableActivePathAlloc(allocator, state_path);
    defer allocator.free(active_path);
    const disabled_path = try selfDisableDisabledPathAlloc(allocator, state_path);
    defer allocator.free(disabled_path);
    std.fs.cwd().deleteFile(state_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    std.fs.cwd().deleteFile(active_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    std.fs.cwd().deleteFile(disabled_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
}

fn defaultSelfDisableStatePath(allocator: std.mem.Allocator) ![]u8 {
    return switch (builtin.os.tag) {
        .macos => macosSelfDisableStatePath(allocator),
        .linux => linuxSelfDisableStatePath(allocator),
        else => linuxSelfDisableStatePath(allocator),
    };
}

fn macosSelfDisableStatePath(allocator: std.mem.Allocator) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/Library/Application Support/shisa/supervisor.state", .{home});
}

fn linuxSelfDisableStatePath(allocator: std.mem.Allocator) ![]u8 {
    const state_home = std.process.getEnvVarOwned(allocator, "XDG_STATE_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (state_home) |path| {
        defer allocator.free(path);
        return std.fmt.allocPrint(allocator, "{s}/shisa/supervisor.state", .{path});
    }
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/supervisor.state", .{home});
}

fn selfDisableActivePathAlloc(allocator: std.mem.Allocator, state_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.active", .{state_path});
}

fn selfDisableDisabledPathAlloc(allocator: std.mem.Allocator, state_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.disabled", .{state_path});
}

fn pathExists(path: []const u8) bool {
    std.fs.cwd().access(path, .{}) catch return false;
    return true;
}

fn writeTextFile(path: []const u8, data: []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.cwd().createFile(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(data);
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
        } else if (std.mem.eql(u8, arg, "--self-disable-state")) {
            config.self_disable_state_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--max-restarts")) {
            config.max_restarts = try parseU32(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--backoff-ms")) {
            config.backoff_ms = try parseU64(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--max-backoff-ms")) {
            config.max_backoff_ms = try parseU64(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--heartbeat-ms")) {
            config.heartbeat_ms = try parseU64(try nextValue(args, &i));
        } else if (std.mem.eql(u8, arg, "--no-self-disable")) {
            config.self_disable = false;
        } else if (std.mem.eql(u8, arg, "--reset-disable")) {
            config.reset_disable = true;
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
        "--self-disable-state",
        "/tmp/supervisor.state",
        "--reset-disable",
    };
    const config = try parse(args[0..]);
    try std.testing.expectEqualStrings("/tmp/shisad", config.daemon_path.?);
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
    try std.testing.expectEqual(@as(u32, 3), config.max_restarts.?);
    try std.testing.expectEqual(@as(u64, 25), config.backoff_ms);
    try std.testing.expectEqual(@as(u64, 100), config.max_backoff_ms);
    try std.testing.expectEqual(@as(u64, 50), config.heartbeat_ms);
    try std.testing.expectEqualStrings("/tmp/supervisor.state", config.self_disable_state_path.?);
    try std.testing.expect(config.reset_disable);
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

test "consecutive restart backoff increases and caps" {
    var backoff_ms: u64 = 100;
    backoff_ms = nextBackoffMs(backoff_ms, 250);
    try std.testing.expectEqual(@as(u64, 200), backoff_ms);
    backoff_ms = nextBackoffMs(backoff_ms, 250);
    try std.testing.expectEqual(@as(u64, 250), backoff_ms);
    backoff_ms = nextBackoffMs(backoff_ms, 250);
    try std.testing.expectEqual(@as(u64, 250), backoff_ms);
}

test "heartbeat miss delay follows heartbeat interval" {
    try std.testing.expectEqual(@as(u64, 150), heartbeatKillDelayMs(50));
    try std.testing.expectEqual(@as(u64, 3000), heartbeatKillDelayMs(1000));
}

test "clean exit treats zero status as graceful" {
    try std.testing.expect(cleanExit(.{ .Exited = 0 }));
    try std.testing.expect(!cleanExit(.{ .Exited = 1 }));
    try std.testing.expect(!cleanExit(.{ .Signal = 15 }));
}

test "heartbeat response accepts legacy and JSON health" {
    try std.testing.expect(try heartbeatResponseOk(std.testing.allocator, "ok\n"));
    try std.testing.expect(try heartbeatResponseOk(std.testing.allocator, "{\"v\":1,\"ok\":true}"));
    try std.testing.expect(!(try heartbeatResponseOk(std.testing.allocator, "{\"v\":1,\"ok\":false}")));
    try std.testing.expect(!(try heartbeatResponseOk(std.testing.allocator, "bad\n")));
}

test "self-disable trips after repeated unclean supervisor exits" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-supervisor-self-disable-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const state_path = try std.fmt.allocPrint(allocator, "{s}/supervisor.state", .{dir_path});
    defer allocator.free(state_path);
    const active_path = try selfDisableActivePathAlloc(allocator, state_path);
    defer allocator.free(active_path);
    const disabled_path = try selfDisableDisabledPathAlloc(allocator, state_path);
    defer allocator.free(disabled_path);

    try writeTextFile(active_path, "active\n");
    try std.testing.expect(!try enterSelfDisableGuard(allocator, state_path, active_path));
    try std.testing.expect(!try enterSelfDisableGuard(allocator, state_path, active_path));
    try std.testing.expect(try enterSelfDisableGuard(allocator, state_path, active_path));
    try std.testing.expect(pathExists(disabled_path));

    try clearSelfDisableState(allocator, state_path);
    try std.testing.expect(!pathExists(disabled_path));
}
