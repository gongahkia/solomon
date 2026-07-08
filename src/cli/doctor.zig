const std = @import("std");
const builtin = @import("builtin");
const cli_util = @import("util.zig");
const client = @import("../shisa-client.zig");
const fsnotify = @import("../daemon/fsnotify.zig");
const paths = @import("../daemon/paths.zig");
const plugin_lua = @import("../plugin/lua.zig");
const plugin_manifest = @import("../plugin/manifest.zig");
const redact = @import("../redact.zig");

const DoctorConfig = struct {
    socket_path: ?[]const u8 = null,
};

const DeprecationRule = struct {
    kind: []const u8,
    pattern: []const u8,
    replacement: []const u8,
    since: []const u8,
    remove_before: []const u8,
};

const active_deprecation_rules = [_]DeprecationRule{};

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseDoctorArgs(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    const output = try doctorOutputAlloc(allocator, socket_path);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseDoctorArgs(args: []const []const u8) !DoctorConfig {
    var config = DoctorConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--socket")) {
            config.socket_path = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownDoctorArgument;
        }
    }
    return config;
}

fn doctorOutputAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const config_dir = try cli_util.configDirPath(allocator);
    defer allocator.free(config_dir);
    const plugins_dir = try cli_util.pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    const daemon_status = try daemonHealthStatusAlloc(allocator, socket_path);
    defer allocator.free(daemon_status);

    try cli_util.appendFmt(allocator, &out, "socket: {s} {s}\n", .{ pathAccessStatus(socket_path), socket_path });
    try cli_util.appendFmt(allocator, &out, "daemon: {s}\n", .{daemon_status});
    try cli_util.appendFmt(allocator, &out, "config_dir: {s} {s}\n", .{ pathAccessStatus(config_dir), config_dir });
    try cli_util.appendFmt(allocator, &out, "plugins_dir: {s} {s}\n", .{ pathAccessStatus(plugins_dir), plugins_dir });
    const plugins_status = try doctorPluginsStatusAlloc(allocator, plugins_dir);
    defer allocator.free(plugins_status);
    try cli_util.appendFmt(allocator, &out, "plugins: {s}\n", .{plugins_status});
    try cli_util.appendFmt(allocator, &out, "lua: {s}\n", .{luaRuntimeStatus(allocator)});
    try cli_util.appendFmt(allocator, &out, "fsnotify: {s}\n", .{fsnotifyBackendName(fsnotify.selectBackend(builtin.os.tag))});
    try appendDoctorDeprecations(allocator, &out, config_path);

    if (builtin.os.tag == .linux) {
        const limit = fsnotify.readLinuxMaxUserWatches(allocator) catch null;
        if (limit) |value| {
            try cli_util.appendFmt(allocator, &out, "inotify.max_user_watches: {d}\n", .{value});
        } else {
            try out.appendSlice(allocator, "inotify.max_user_watches: unknown\n");
        }
    }

    return out.toOwnedSlice(allocator);
}

fn doctorPluginsStatusAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8) ![]u8 {
    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "none"),
        else => return std.fmt.allocPrint(allocator, "unreadable ({s})", .{@errorName(err)}),
    };
    defer dir.close();

    var names: std.ArrayList([]u8) = .empty;
    defer {
        for (names.items) |name| allocator.free(name);
        names.deinit(allocator);
    }

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!plugin_manifest.isValidPluginName(entry.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, entry.name));
    }
    if (names.items.len == 0) return allocator.dupe(u8, "none");

    std.mem.sort([]u8, names.items, {}, lessThanString);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (names.items, 0..) |name, i| {
        if (i != 0) try out.appendSlice(allocator, ",");
        try out.appendSlice(allocator, name);
    }
    return out.toOwnedSlice(allocator);
}

fn appendDoctorDeprecations(allocator: std.mem.Allocator, out: *std.ArrayList(u8), config_path: []const u8) !void {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch |err| {
        try cli_util.appendFmt(allocator, out, "deprecations: unreadable ({s})\n", .{@errorName(err)});
        return;
    };
    defer allocator.free(source);

    const warnings = try deprecationWarningsAlloc(allocator, source, active_deprecation_rules[0..]);
    defer allocator.free(warnings);
    try out.appendSlice(allocator, warnings);
}

fn deprecationWarningsAlloc(allocator: std.mem.Allocator, source: []const u8, rules: []const DeprecationRule) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    var count: usize = 0;
    for (rules) |rule| {
        if (std.mem.indexOf(u8, source, rule.pattern) == null) continue;
        try cli_util.appendFmt(
            allocator,
            &out,
            "deprecation: {s} `{s}` deprecated since {s}; use `{s}`; remove before {s}\n",
            .{ rule.kind, rule.pattern, rule.since, rule.replacement, rule.remove_before },
        );
        count += 1;
    }
    if (count == 0) try out.appendSlice(allocator, "deprecations: none\n");
    return out.toOwnedSlice(allocator);
}

const report_max_log_bytes = 1024 * 1024;
const report_bench_iterations = 8;

const report_help_text =
    \\usage: shisa report [--output path]
    \\
    \\options:
    \\  -o, --output <path> write bundle path; defaults to ./shisa-report-<timestamp>.tar.gz
    \\
;

pub const ReportBench = struct {
    version: []const u8,
    iteration: *const fn (std.mem.Allocator) anyerror![]u8,
};

const ReportConfig = struct {
    output_path: ?[]const u8 = null,
};

pub fn reportCommand(allocator: std.mem.Allocator, args: []const []const u8, bench: ReportBench) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(report_help_text);
        return;
    }

    const config = try parseReportArgs(args);
    const output_path = if (config.output_path) |path| path else try defaultReportPathAlloc(allocator);
    defer if (config.output_path == null) allocator.free(output_path);

    const staging_dir = try reportStagingDirAlloc(allocator);
    defer allocator.free(staging_dir);
    defer std.fs.cwd().deleteTree(staging_dir) catch {};
    try std.fs.cwd().makePath(staging_dir);

    try writeReportBundleFiles(allocator, staging_dir, bench);
    try createReportArchive(allocator, staging_dir, output_path);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{output_path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn parseReportArgs(args: []const []const u8) !ReportConfig {
    var config = ReportConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--output") or std.mem.eql(u8, args[i], "-o")) {
            config.output_path = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownReportArgument;
        }
    }
    return config;
}

fn defaultReportPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "shisa-report-{d}.tar.gz", .{std.time.timestamp()});
}

fn reportStagingDirAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "/tmp/shisa-report-{x}", .{std.crypto.random.int(u64)});
}

fn writeReportBundleFiles(allocator: std.mem.Allocator, staging_dir: []const u8, bench: ReportBench) !void {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const log_path = try paths.defaultLogPath(allocator);
    defer allocator.free(log_path);

    const manifest = try reportManifestAlloc(allocator, config_path, log_path);
    defer allocator.free(manifest);
    try writeReportFile(allocator, staging_dir, "README.txt", manifest);

    const config_text = try reportConfigRedactedAlloc(allocator, config_path);
    defer allocator.free(config_text);
    try writeReportFile(allocator, staging_dir, "config.redacted.toml", config_text);

    const log_text = try reportLogRedactedAlloc(allocator, log_path);
    defer allocator.free(log_text);
    try writeReportFile(allocator, staging_dir, "shisad.log.redacted", log_text);

    const bench_text = try reportBenchAlloc(allocator, bench);
    defer allocator.free(bench_text);
    try writeReportFile(allocator, staging_dir, "bench.txt", bench_text);
}

fn reportManifestAlloc(allocator: std.mem.Allocator, config_path: []const u8, log_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\Shisa support bundle
        \\
        \\Files:
        \\- config.redacted.toml: active config from {s}, or built-in defaults when missing
        \\- shisad.log.redacted: last 1MiB of {s}, or missing/unreadable status
        \\- bench.txt: local prompt payload microbench metadata
        \\
        \\Redaction:
        \\Values matching documented secret patterns are replaced with [redacted] before archive creation.
        \\
    , .{ config_path, log_path });
}

fn reportConfigRedactedAlloc(allocator: std.mem.Allocator, config_path: []const u8) ![]u8 {
    const raw = try cli_util.readConfigOrDefault(allocator, config_path);
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn reportLogRedactedAlloc(allocator: std.mem.Allocator, log_path: []const u8) ![]u8 {
    const raw = readFileTailAlloc(allocator, log_path, report_max_log_bytes) catch |err| switch (err) {
        error.FileNotFound => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: missing\n", .{log_path}),
        else => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: unreadable\nerror: {s}\n", .{ log_path, @errorName(err) }),
    };
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn redactReportDataAlloc(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    return redact.redactAlloc(allocator, data);
}

fn readFileTailAlloc(allocator: std.mem.Allocator, path: []const u8, max_bytes: usize) ![]u8 {
    var file = try std.fs.openFileAbsolute(path, .{});
    defer file.close();
    const end = try file.getEndPos();
    const start = if (end > max_bytes) end - max_bytes else 0;
    try file.seekTo(start);
    return file.readToEndAlloc(allocator, max_bytes);
}

fn reportBenchAlloc(allocator: std.mem.Allocator, bench: ReportBench) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try cli_util.appendFmt(allocator, &out, "version: {s}\n", .{bench.version});
    try cli_util.appendFmt(allocator, &out, "os: {s}\n", .{@tagName(builtin.os.tag)});
    try cli_util.appendFmt(allocator, &out, "iterations: {d}\n", .{report_bench_iterations});

    var total_ns: u64 = 0;
    var min_ns: u64 = std.math.maxInt(u64);
    var max_ns: u64 = 0;
    for (0..report_bench_iterations) |_| {
        const start = std.time.nanoTimestamp();
        const payload = bench.iteration(allocator) catch |err| {
            try cli_util.appendFmt(allocator, &out, "status: failed\nerror: {s}\n", .{@errorName(err)});
            return out.toOwnedSlice(allocator);
        };
        defer allocator.free(payload);
        const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
        total_ns += elapsed;
        min_ns = @min(min_ns, elapsed);
        max_ns = @max(max_ns, elapsed);
    }
    try out.appendSlice(allocator, "status: ok\n");
    try cli_util.appendFmt(allocator, &out, "avg_ns: {d}\n", .{total_ns / report_bench_iterations});
    try cli_util.appendFmt(allocator, &out, "min_ns: {d}\n", .{min_ns});
    try cli_util.appendFmt(allocator, &out, "max_ns: {d}\n", .{max_ns});
    return out.toOwnedSlice(allocator);
}

fn writeReportFile(allocator: std.mem.Allocator, staging_dir: []const u8, name: []const u8, data: []const u8) !void {
    const path = try std.fs.path.join(allocator, &.{ staging_dir, name });
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(data);
}

fn createReportArchive(allocator: std.mem.Allocator, staging_dir: []const u8, output_path: []const u8) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "tar", "-czf", output_path, "-C", staging_dir, "." },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa report: tar not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.ReportArchiveFailed;
}

test "report args parse output path" {
    const config = try parseReportArgs(&.{ "--output", "/tmp/shisa-report.tar.gz" });
    try std.testing.expectEqualStrings("/tmp/shisa-report.tar.gz", config.output_path.?);
}

test "report redaction scrubs documented patterns" {
    const input =
        \\password = "hunter2"
        \\Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig
        \\AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        \\aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        \\github=ghp_abcdefghijklmnopqrstuvwxyz1234567890
        \\openai=sk-abcdefghijklmnopqrst
        \\account=123456789012
        \\IdentityFile ~/.ssh/id_rsa
        \\client-key-data: kube-secret
        \\-----BEGIN OPENSSH PRIVATE KEY-----
        \\abc123
        \\-----END OPENSSH PRIVATE KEY-----
        \\
    ;
    const output = try redactReportDataAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(output);

    inline for (.{
        "hunter2",
        "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "sk-abcdefghijklmnopqrst",
        "123456789012",
        "~/.ssh/id_rsa",
        "kube-secret",
        "abc123",
    }) |secret| {
        try std.testing.expect(std.mem.indexOf(u8, output, secret) == null);
    }
    try std.testing.expect(std.mem.indexOf(u8, output, redact.marker) != null);
}

fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
}

fn daemonHealthStatusAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    const response = client.requestAlloc(allocator, socket_path, "health\n") catch |err| return daemonHealthErrorStatusAlloc(allocator, err);
    defer allocator.free(response);
    const trimmed = std.mem.trim(u8, response, " \t\r\n");
    if (std.mem.eql(u8, trimmed, "ok")) return allocator.dupe(u8, "ok");
    return allocator.dupe(u8, "bad-response");
}

fn daemonHealthErrorStatusAlloc(allocator: std.mem.Allocator, err: anyerror) ![]u8 {
    return switch (err) {
        error.FileNotFound => allocator.dupe(u8, "socket-missing"),
        error.ConnectionRefused => std.fmt.allocPrint(allocator, "not-reachable ({s})", .{@errorName(err)}),
        error.WouldBlock, error.NetworkUnreachable => std.fmt.allocPrint(allocator, "not-reachable ({s})", .{@errorName(err)}),
        else => std.fmt.allocPrint(allocator, "error ({s})", .{@errorName(err)}),
    };
}

fn luaRuntimeStatus(allocator: std.mem.Allocator) []const u8 {
    var runtime = plugin_lua.Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return "unavailable",
        else => return "error",
    };
    runtime.deinit();
    return "available";
}

fn fsnotifyBackendName(backend: fsnotify.Backend) []const u8 {
    return switch (backend) {
        .fsevents => "fsevents",
        .inotify => "inotify",
        .unsupported => "unsupported",
    };
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

test "doctor args parse socket override" {
    const config = try parseDoctorArgs(&.{ "--socket", "/tmp/shisa.sock" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
}

test "doctor reports path and backend statuses" {
    try std.testing.expectEqualStrings("missing", pathAccessStatus("/tmp/shisa-doctor-missing"));
    try std.testing.expectEqualStrings("fsevents", fsnotifyBackendName(.fsevents));
    try std.testing.expectEqualStrings("inotify", fsnotifyBackendName(.inotify));
}

test "doctor reports installed plugins" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    const dir_path = try tmp.dir.realpathAlloc(std.testing.allocator, ".");
    defer std.testing.allocator.free(dir_path);
    try tmp.dir.makePath("beta");
    try tmp.dir.makePath("alpha");
    try tmp.dir.makePath("Bad");

    const output = try doctorPluginsStatusAlloc(std.testing.allocator, dir_path);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("alpha,beta", output);
}

test "doctor reports missing daemon socket clearly" {
    const socket_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-doctor-missing-{x}.sock", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(socket_path);
    std.fs.cwd().deleteFile(socket_path) catch {};

    const status = try daemonHealthStatusAlloc(std.testing.allocator, socket_path);
    defer std.testing.allocator.free(status);
    try std.testing.expectEqualStrings("socket-missing", status);
}

test "doctor deprecation scanner reports matching rules" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "old_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "deprecation: config `old_key` deprecated since 1.4.0") != null);
}

test "doctor deprecation scanner reports none" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "new_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("deprecations: none\n", output);
}
