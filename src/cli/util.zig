const std = @import("std");
const shisa_config = @import("../config.zig");

/// maximum config bytes read by helpers that load shisa.toml.
pub const max_config_bytes = 1024 * 1024;

/// builds the default shisa.toml path from the process environment.
/// caller owns the returned slice and must free it with allocator.
/// environment: prefers XDG_CONFIG_HOME; falls back to HOME.
/// errors: EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn defaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
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

/// builds the default shisa.toml path from already-read environment values.
/// xdg_config_home and home are borrowed and are not retained.
/// caller owns the returned slice and must free it with allocator.
/// errors: MissingHome when both inputs are null; OutOfMemory on allocation failure.
pub fn defaultConfigPathFromEnv(allocator: std.mem.Allocator, xdg_config_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_config_home) |base| return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{base});
    if (home) |base| return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{base});
    return error.MissingHome;
}

/// reads a config file or returns the built-in default config when the file is absent.
/// path must be an absolute path; caller owns the returned slice and must free it with allocator.
/// errors: filesystem open/read errors except FileNotFound; FileTooBig when the file exceeds max_config_bytes; OutOfMemory on allocation failure.
pub fn readConfigOrDefault(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, shisa_config.default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

/// builds the directory path that contains the default shisa.toml.
/// caller owns the returned slice and must free it with allocator.
/// environment: follows defaultConfigPath, including XDG_CONFIG_HOME and HOME.
/// errors: MissingConfigDir if the config path has no dirname; plus defaultConfigPath errors.
pub fn configDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return allocator.dupe(u8, dir);
}

/// builds the configured plugin directory path.
/// caller owns the returned slice and must free it with allocator.
/// environment: follows configDirPath, including XDG_CONFIG_HOME and HOME.
/// errors: MissingConfigDir from configDirPath; EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn pluginsDirPath(allocator: std.mem.Allocator) ![]u8 {
    const dir = try configDirPath(allocator);
    defer allocator.free(dir);
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

/// returns a compact access status for a path relative to the current process.
/// path is borrowed and no allocation occurs.
/// errors: none; FileNotFound maps to "missing", AccessDenied maps to "denied", and other access errors map to "error".
pub fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
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

/// appends formatted text to an ArrayList.
/// out must remain valid for the call; args follow std.fmt.allocPrint semantics.
/// ownership: temporary formatted storage is freed before return; out retains appended bytes.
/// errors: OutOfMemory from formatting or appending.
pub fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

/// consumes and returns the next CLI argument after index.
/// args is borrowed; index is advanced only when a value exists.
/// ownership: returned slice aliases args and must not be freed.
/// errors: MissingValue when there is no following argument.
pub fn nextValue(args: []const []const u8, index: *usize) ![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

/// reports whether a child-process termination value is exit code 0.
/// term is borrowed by value and no allocation occurs.
/// errors: none.
pub fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

/// runs a git-style command in cwd_path and returns stdout when it exits 0.
/// argv and cwd_path are borrowed for the call; argv[0] is expanded through PATH.
/// caller owns the returned stdout slice and must free it with allocator.
/// errors: CommandFailed for non-zero exits; process spawn errors such as FileNotFound; OutOfMemory on allocation failure.
pub fn gitOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.CommandFailed;
    }
    return result.stdout;
}

/// escapes a UTF-8 byte slice for JSON string content.
/// value is borrowed; caller owns the returned slice and must free it with allocator.
/// errors: OutOfMemory on allocation failure.
pub fn jsonEscapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
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
