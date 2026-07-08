const std = @import("std");
const cli_util = @import("util.zig");

pub fn benchCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const bench_config = try parseBench(args);
    try ensureHyperfine(allocator);

    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const daemon_path = try cli_util.siblingExecutablePath(allocator, "shisad");
    defer allocator.free(daemon_path);
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    const socket_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.sock", .{std.crypto.random.int(u64)});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.log", .{std.crypto.random.int(u64)});
    defer allocator.free(log_path);
    defer std.fs.deleteFileAbsolute(socket_path) catch {};
    defer std.fs.deleteFileAbsolute(log_path) catch {};

    var daemon = std.process.Child.init(&.{ daemon_path, "--foreground", "--socket", socket_path, "--log", log_path }, allocator);
    daemon.stdin_behavior = .Ignore;
    daemon.stdout_behavior = .Ignore;
    daemon.stderr_behavior = .Ignore;
    try daemon.spawn();
    defer _ = daemon.kill() catch {};

    try cli_util.waitForPath(socket_path, 1000);
    const workload = try benchWorkloadAlloc(allocator, self_path, socket_path, cwd);
    defer allocator.free(workload);
    try runHyperfine(allocator, workload, bench_config);
}

const BenchConfig = struct {
    export_json: ?[]const u8 = null,
};

fn parseBench(args: []const []const u8) !BenchConfig {
    var config = BenchConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--export-json")) {
            config.export_json = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownBenchArgument;
        }
    }
    return config;
}

fn ensureHyperfine(allocator: std.mem.Allocator) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "hyperfine", "--version" },
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa bench: hyperfine not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.HyperfineUnavailable;
}

fn runHyperfine(allocator: std.mem.Allocator, workload: []const u8, bench_config: BenchConfig) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "hyperfine", "--warmup", "5", "--runs", "25" });
    if (bench_config.export_json) |path| {
        try argv.appendSlice(allocator, &.{ "--export-json", path });
    }
    try argv.append(allocator, workload);

    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv.items,
        .max_output_bytes = 8 * 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);

    try std.fs.File.stdout().writeAll(result.stdout);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.BenchmarkFailed;
}

fn benchWorkloadAlloc(allocator: std.mem.Allocator, self_path: []const u8, socket_path: []const u8, cwd: []const u8) ![]u8 {
    const quoted_self = try cli_util.shellSingleQuoteAlloc(allocator, self_path);
    defer allocator.free(quoted_self);
    const quoted_socket = try cli_util.shellSingleQuoteAlloc(allocator, socket_path);
    defer allocator.free(quoted_socket);
    const quoted_cwd = try cli_util.shellSingleQuoteAlloc(allocator, cwd);
    defer allocator.free(quoted_cwd);
    return std.fmt.allocPrint(
        allocator,
        "{s} prompt --socket {s} --cwd {s} --shell zsh --cols 80 --rows 24",
        .{ quoted_self, quoted_socket, quoted_cwd },
    );
}

test "bench workload targets prompt command" {
    const workload = try benchWorkloadAlloc(std.testing.allocator, "/tmp/shisa", "/tmp/sock", "/tmp/repo");
    defer std.testing.allocator.free(workload);
    try std.testing.expectEqualStrings("'/tmp/shisa' prompt --socket '/tmp/sock' --cwd '/tmp/repo' --shell zsh --cols 80 --rows 24", workload);
}

test "parses bench export json flag" {
    const args = [_][]const u8{ "--export-json", "/tmp/out.json" };
    const config = try parseBench(args[0..]);
    try std.testing.expectEqualStrings("/tmp/out.json", config.export_json.?);
}
