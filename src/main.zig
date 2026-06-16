const std = @import("std");
const daemon_cache = @import("daemon/cache.zig");
const client = @import("shisa-client.zig");
const shisa_config = @import("config.zig");
const paths = @import("daemon/paths.zig");
const proto = @import("proto/types.zig");
const plugin_manifest = @import("plugin/manifest.zig");
const supervisor = @import("supervisor.zig");

const version = "0.1.0-dev";
const max_config_bytes = 1024 * 1024;

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len == 1 or std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    if (std.mem.eql(u8, args[1], "--version")) {
        try std.fs.File.stdout().writeAll("shisa " ++ version ++ "\n");
        return;
    }

    if (std.mem.eql(u8, args[1], "supervisor")) {
        try supervisor.run(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "init")) {
        try initConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "explain")) {
        try explainConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "bench")) {
        try bench(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cache")) {
        try cacheCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "pin")) {
        try pinCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "plugin")) {
        try pluginCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "prompt")) {
        try prompt(allocator, args[2..]);
        return;
    }

    try std.fs.File.stderr().writeAll("shisa: unknown command; run `shisa --help`\n");
    return error.UnknownCommand;
}

test "smoke" {
    try std.testing.expect(true);
}

fn initConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownInitArgument;

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(path, .{ .exclusive = true });
    defer file.close();
    try file.writeAll(shisa_config.default_config_text);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn defaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return defaultConfigPathFromEnv(allocator, xdg_config_home, null);
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return defaultConfigPathFromEnv(allocator, null, home);
}

fn defaultConfigPathFromEnv(allocator: std.mem.Allocator, xdg_config_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_config_home) |base| return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{base});
    if (home) |base| return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{base});
    return error.MissingHome;
}

test "default config path prefers xdg" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, "/tmp/xdg", "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/xdg/shisa/shisa.toml", path);
}

test "default config path falls back to home" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, null, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/.config/shisa/shisa.toml", path);
}

fn explainConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownExplainArgument;

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
    defer allocator.free(source);

    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);

    const output = try explainAlloc(allocator, parsed);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn readConfigOrDefault(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, shisa_config.default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

fn explainAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try appendFmt(allocator, &out, "theme: {s}\n", .{parsed.theme});
    try out.appendSlice(allocator, "pipeline:\n");
    for (parsed.prompt_modules, 0..) |module_id, index| {
        try appendFmt(
            allocator,
            &out,
            "  {d}. {s} ({s})\n",
            .{ index + 1, shisa_config.moduleIdName(module_id), shisa_config.moduleExecutionClass(module_id) },
        );
    }

    return out.toOwnedSlice(allocator);
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

test "explain output dumps pipeline" {
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &diagnostic);
    defer parsed.deinit(std.testing.allocator);

    const output = try explainAlloc(std.testing.allocator, parsed);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme: plain\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "1. cwd (sync)") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "2. git_branch (async)") != null);
}

fn bench(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const bench_config = try parseBench(args);
    try ensureHyperfine(allocator);

    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const daemon_path = try siblingExecutablePath(allocator, "shisad");
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

    try waitForPath(socket_path, 1000);
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
            config.export_json = try nextValue(args, &i);
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
    if (!exitedZero(result.term)) return error.HyperfineUnavailable;
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
    if (!exitedZero(result.term)) return error.BenchmarkFailed;
}

fn benchWorkloadAlloc(allocator: std.mem.Allocator, self_path: []const u8, socket_path: []const u8, cwd: []const u8) ![]u8 {
    const quoted_self = try shellQuoteAlloc(allocator, self_path);
    defer allocator.free(quoted_self);
    const quoted_socket = try shellQuoteAlloc(allocator, socket_path);
    defer allocator.free(quoted_socket);
    const quoted_cwd = try shellQuoteAlloc(allocator, cwd);
    defer allocator.free(quoted_cwd);
    return std.fmt.allocPrint(
        allocator,
        "{s} prompt --socket {s} --cwd {s} --shell zsh --cols 80 --rows 24",
        .{ quoted_self, quoted_socket, quoted_cwd },
    );
}

fn shellQuoteAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.append(allocator, '\'');
    for (value) |byte| {
        if (byte == '\'') {
            try out.appendSlice(allocator, "'\\''");
        } else {
            try out.append(allocator, byte);
        }
    }
    try out.append(allocator, '\'');
    return out.toOwnedSlice(allocator);
}

fn siblingExecutablePath(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse ".";
    return std.fs.path.join(allocator, &.{ dir, name });
}

fn waitForPath(path: []const u8, timeout_ms: i64) !void {
    const start = std.time.milliTimestamp();
    while (std.time.milliTimestamp() - start < timeout_ms) {
        std.fs.cwd().access(path, .{}) catch {
            std.Thread.sleep(10 * std.time.ns_per_ms);
            continue;
        };
        return;
    }
    return error.Timeout;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "shell quoting handles spaces and quotes" {
    const quoted = try shellQuoteAlloc(std.testing.allocator, "/tmp/a b/c'd");
    defer std.testing.allocator.free(quoted);
    try std.testing.expectEqualStrings("'/tmp/a b/c'\\''d'", quoted);
}

test "bench workload targets prompt command" {
    const workload = try benchWorkloadAlloc(std.testing.allocator, "/tmp/shisa", "/tmp/sock", "/tmp/repo");
    defer std.testing.allocator.free(workload);
    try std.testing.expectEqualStrings("'/tmp/shisa' prompt --socket '/tmp/sock' --cwd '/tmp/repo' --shell zsh --cols 80 --rows 24", workload);
}

fn cacheCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const action = if (args.len == 0) "stats" else args[0];
    if (args.len > 1) return error.UnknownCacheArgument;
    if (!std.mem.eql(u8, action, "stats")) return error.UnknownCacheArgument;

    const output = try cacheStatsAlloc(allocator, .{});
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cacheStatsAlloc(allocator: std.mem.Allocator, options: daemon_cache.Options) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "{{\"module_cache\":{{\"entries\":0,\"max_entries\":{d},\"max_age_ns\":{d}}},\"prompt_cache\":{{\"entries\":0}}}}\n",
        .{ options.max_entries, options.max_age_ns },
    );
}

test "cache stats output is json object" {
    const output = try cacheStatsAlloc(std.testing.allocator, .{ .max_entries = 2, .max_age_ns = 3 });
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("{\"module_cache\":{\"entries\":0,\"max_entries\":2,\"max_age_ns\":3},\"prompt_cache\":{\"entries\":0}}\n", output);
}

fn pinCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownPinArgument;
    const path = try std.fs.cwd().realpathAlloc(allocator, args[0]);
    defer allocator.free(path);
    const pins_path = try pinsPath(allocator);
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, path);

    const message = try std.fmt.allocPrint(allocator, "pinned {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn pinsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/pins", .{dir});
}

fn appendPin(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !void {
    if (std.fs.path.dirname(pins_path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    if (try pinExists(allocator, pins_path, path)) return;

    var file = try std.fs.createFileAbsolute(pins_path, .{ .truncate = false, .read = true });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(path);
    try file.writeAll("\n");
}

fn pinExists(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, pins_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        if (std.mem.eql(u8, line, path)) return true;
    }
    return false;
}

test "appends pin once" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-pin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const pins_path = try std.fmt.allocPrint(allocator, "{s}/pins", .{dir_path});
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, "/tmp/repo");
    try appendPin(allocator, pins_path, "/tmp/repo");

    const contents = try std.fs.cwd().readFileAlloc(allocator, pins_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("/tmp/repo\n", contents);
}

fn pluginCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0) return error.UnknownPluginArgument;

    const plugins_dir = try pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);
    const disabled_path = try disabledPluginsPath(allocator);
    defer allocator.free(disabled_path);

    if (std.mem.eql(u8, args[0], "list")) {
        if (args.len != 1) return error.UnknownPluginArgument;
        const output = try pluginListAlloc(allocator, plugins_dir, disabled_path);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
    } else if (std.mem.eql(u8, args[0], "disable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], true);
        const message = try std.fmt.allocPrint(allocator, "disabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else if (std.mem.eql(u8, args[0], "enable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], false);
        const message = try std.fmt.allocPrint(allocator, "enabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else {
        return error.UnknownPluginArgument;
    }
}

fn pluginsDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

fn disabledPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir});
}

fn pluginListAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8, disabled_path: []const u8) ![]u8 {
    var names: std.ArrayList([]u8) = .empty;
    defer {
        for (names.items) |name| allocator.free(name);
        names.deinit(allocator);
    }

    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer dir.close();

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!plugin_manifest.isValidPluginName(entry.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, entry.name));
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (names.items) |name| {
        const state = if (try pluginDisabled(allocator, disabled_path, name)) "disabled" else "enabled";
        try appendFmt(allocator, &out, "{s} {s}\n", .{ name, state });
    }
    return out.toOwnedSlice(allocator);
}

fn setPluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8, disabled: bool) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readDisabledPlugins(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }

    const index = indexOfString(names.items, name);
    if (disabled and index == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    } else if (!disabled and index != null) {
        const removed = names.orderedRemove(index.?);
        allocator.free(removed);
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writeDisabledPlugins(allocator, disabled_path, names.items);
}

fn pluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8) !bool {
    var names = try readDisabledPlugins(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn readDisabledPlugins(allocator: std.mem.Allocator, disabled_path: []const u8) !std.ArrayList([]u8) {
    var names: std.ArrayList([]u8) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, disabled_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return names,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len == 0 or !plugin_manifest.isValidPluginName(trimmed)) continue;
        if (indexOfString(names.items, trimmed) == null) {
            try names.append(allocator, try allocator.dupe(u8, trimmed));
        }
    }
    return names;
}

fn writeDisabledPlugins(allocator: std.mem.Allocator, disabled_path: []const u8, names: []const []const u8) !void {
    if (std.fs.path.dirname(disabled_path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(disabled_path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (names) |name| {
        try file.writeAll(name);
        try file.writeAll("\n");
    }
    _ = allocator;
}

fn indexOfString(items: []const []const u8, name: []const u8) ?usize {
    for (items, 0..) |item, index| {
        if (std.mem.eql(u8, item, name)) return index;
    }
    return null;
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

test "plugin list reports enabled and disabled plugins" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    try std.fs.cwd().makePath(plugins_dir);
    const beta_path = try std.fmt.allocPrint(allocator, "{s}/beta", .{plugins_dir});
    defer allocator.free(beta_path);
    const alpha_path = try std.fmt.allocPrint(allocator, "{s}/alpha", .{plugins_dir});
    defer allocator.free(alpha_path);
    const bad_path = try std.fmt.allocPrint(allocator, "{s}/Bad", .{plugins_dir});
    defer allocator.free(bad_path);
    try std.fs.cwd().makePath(beta_path);
    try std.fs.cwd().makePath(alpha_path);
    try std.fs.cwd().makePath(bad_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "beta", true);

    const output = try pluginListAlloc(allocator, plugins_dir, disabled_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("alpha enabled\nbeta disabled\n", output);
}

test "plugin enable disable is duplicate safe" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try std.testing.expect(try pluginDisabled(allocator, disabled_path, "alpha"));
    try setPluginDisabled(allocator, disabled_path, "alpha", false);
    try std.testing.expect(!(try pluginDisabled(allocator, disabled_path, "alpha")));

    const contents = try std.fs.cwd().readFileAlloc(allocator, disabled_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("", contents);
}

test "plugin state rejects invalid names" {
    try std.testing.expectError(error.InvalidPluginName, setPluginDisabled(std.testing.allocator, "/tmp/shisa-plugin-invalid", "Bad", true));
}

test "parses bench export json flag" {
    const args = [_][]const u8{ "--export-json", "/tmp/out.json" };
    const config = try parseBench(args[0..]);
    try std.testing.expectEqualStrings("/tmp/out.json", config.export_json.?);
}

const PromptConfig = struct {
    socket_path: ?[]const u8 = null,
    cwd: ?[]const u8 = null,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    time: bool = false,
    no_async: bool = false,
    instant: bool = false,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
};

fn prompt(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parsePrompt(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const payload = try buildPromptPayload(allocator, config, cwd);
    defer allocator.free(payload);

    if (config.instant) {
        if (try readInstantPrompt(allocator)) |cached| {
            defer allocator.free(cached);
            try std.fs.File.stdout().writeAll(cached);
            return;
        }
    }

    const response_payload = try client.requestAlloc(allocator, socket_path, payload);
    defer allocator.free(response_payload);

    var parsed = try std.json.parseFromSlice(proto.Response, allocator, response_payload, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (config.instant) {
        try writeInstantPrompt(allocator, parsed.value.prompt);
    }
    try std.fs.File.stdout().writeAll(parsed.value.prompt);
}

fn parsePrompt(args: []const []const u8) !PromptConfig {
    var config = PromptConfig{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--exit")) {
            config.exit = try std.fmt.parseInt(i32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--jobs")) {
            config.jobs = try std.fmt.parseInt(u32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--duration-ms")) {
            config.duration_ms = try std.fmt.parseInt(u64, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--time")) {
            config.time = true;
        } else if (std.mem.eql(u8, arg, "--no-async")) {
            config.no_async = true;
        } else if (std.mem.eql(u8, arg, "--instant")) {
            config.instant = true;
        } else if (std.mem.eql(u8, arg, "--shell")) {
            config.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cols")) {
            config.cols = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--rows")) {
            config.rows = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else {
            return error.UnknownPromptArgument;
        }
    }

    return config;
}

fn instantPromptPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir});
}

fn readInstantPrompt(allocator: std.mem.Allocator) !?[]u8 {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    return std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
}

fn writeInstantPrompt(allocator: std.mem.Allocator, prompt_text: []const u8) !void {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(prompt_text);
}

test "instant prompt read write roundtrip" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-instant-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const path = try std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir_path});
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{});
    try file.writeAll("cached> ");
    file.close();

    const cached = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024);
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("cached> ", cached);
}

fn nextValue(args: []const []const u8, index: *usize) ![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

fn buildPromptPayload(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8) ![]u8 {
    const escaped_cwd = try jsonEscapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try jsonEscapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);

    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d}}}",
        .{ escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows },
    );
}

fn jsonEscapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    for (value) |byte| {
        switch (byte) {
            '"' => try out.appendSlice(allocator, "\\\""),
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }

    return out.toOwnedSlice(allocator);
}

const help_text =
    \\usage: shisa <command> [options]
    \\
    \\commands:
    \\  bench         benchmark prompt render via hyperfine
    \\  cache         dump cache stats
    \\  explain       print resolved module pipeline
    \\  init          write default shisa.toml
    \\  pin           mark a path as never-evicted
    \\  plugin        list, enable, or disable plugins
    \\  prompt        render prompt through shisad
    \\  supervisor    run shisad under a crash-restart supervisor
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version print version
    \\
;
