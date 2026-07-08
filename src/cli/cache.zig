const std = @import("std");
const cli_util = @import("util.zig");
const daemon_cache = @import("../daemon/cache.zig");
const daemon_json = @import("../daemon/json.zig");

pub fn cacheCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const action = if (args.len == 0) "stats" else args[0];
    const output = if (std.mem.eql(u8, action, "stats")) stats: {
        if (args.len > 1) return error.UnknownCacheArgument;
        break :stats try cacheStatsAlloc(allocator, .{});
    } else if (std.mem.eql(u8, action, "clear")) clear: {
        const module = try parseCacheClearModule(args[1..]);
        const path = (try cacheClearPathAlloc(allocator)) orelse {
            break :clear try std.fmt.allocPrint(allocator, "{{\"cleared\":false,\"reason\":\"missing_home\"}}\n", .{});
        };
        defer allocator.free(path);
        break :clear try cacheClearOutputAlloc(allocator, path, module);
    } else return error.UnknownCacheArgument;
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

fn parseCacheClearModule(args: []const []const u8) !?[]const u8 {
    var module: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--module")) {
            module = try cli_util.nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--module=")) {
            module = arg["--module=".len..];
        } else {
            return error.UnknownCacheArgument;
        }
    }
    if (module) |value| if (value.len == 0) return error.UnknownCacheArgument;
    return module;
}

fn cacheClearPathAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    defer allocator.free(home);
    return daemon_cache.defaultPersistPathAlloc(allocator, home);
}

fn cacheClearOutputAlloc(allocator: std.mem.Allocator, path: []const u8, module: ?[]const u8) ![]u8 {
    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.loadFromFile(path);
    const before = store.count();
    if (module) |module_id| {
        try store.invalidateModule(module_id);
        if (store.count() == 0) {
            std.fs.deleteFileAbsolute(path) catch |err| switch (err) {
                error.FileNotFound => {},
                else => return err,
            };
        } else {
            try store.saveToFile(path);
        }
        const escaped_module = try daemon_json.escapeAlloc(allocator, module_id);
        defer allocator.free(escaped_module);
        return std.fmt.allocPrint(allocator, "{{\"cleared\":true,\"module\":\"{s}\",\"entries_before\":{d},\"entries_after\":{d}}}\n", .{ escaped_module, before, store.count() });
    }

    store.clear();
    std.fs.deleteFileAbsolute(path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    return std.fmt.allocPrint(allocator, "{{\"cleared\":true,\"module\":null,\"entries_before\":{d},\"entries_after\":0}}\n", .{before});
}

test "cache stats output is json object" {
    const output = try cacheStatsAlloc(std.testing.allocator, .{ .max_entries = 2, .max_age_ns = 3 });
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("{\"module_cache\":{\"entries\":0,\"max_entries\":2,\"max_age_ns\":3},\"prompt_cache\":{\"entries\":0}}\n", output);
}

test "cache clear parses module arg" {
    try std.testing.expectEqualStrings("git_branch", (try parseCacheClearModule(&.{"--module=git_branch"})).?);
    try std.testing.expectEqualStrings("language_versions", (try parseCacheClearModule(&.{ "--module", "language_versions" })).?);
    try std.testing.expect((try parseCacheClearModule(&.{})) == null);
}

test "cache clear removes all persisted entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-clear-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const path = try std.fmt.allocPrint(allocator, "{s}/cache.bin", .{dir_path});
    defer allocator.free(path);

    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.putAt("git_branch", "/repo", "git:main", 1, 1);
    try store.putAt("language_versions", "/repo", "py:3.14", 2, 1);
    try store.saveToFile(path);

    const output = try cacheClearOutputAlloc(allocator, path, null);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"cleared\":true,\"module\":null,\"entries_before\":2,\"entries_after\":0}\n", output);
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(path, .{}));
}

test "cache clear removes one module from persisted entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-clear-module-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const path = try std.fmt.allocPrint(allocator, "{s}/cache.bin", .{dir_path});
    defer allocator.free(path);

    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.putAt("git_branch", "/repo", "git:main", 1, 1);
    try store.putAt("language_versions", "/repo", "py:3.14", 2, 1);
    try store.saveToFile(path);

    const output = try cacheClearOutputAlloc(allocator, path, "git_branch");
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"cleared\":true,\"module\":\"git_branch\",\"entries_before\":2,\"entries_after\":1}\n", output);

    var loaded = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer loaded.deinit();
    try loaded.loadFromFile(path);
    try std.testing.expect(try loaded.getAt("git_branch", "/repo", 2) == null);
    try std.testing.expect((try loaded.getAt("language_versions", "/repo", 2)) != null);
}
